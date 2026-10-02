import hashlib
import re
from pathlib import Path, PurePosixPath
from pydantic import BaseModel, ConfigDict, Field
from .security import secret_present, check_new_capabilities


class Edit(BaseModel):
    model_config = ConfigDict(extra='forbid')
    path: str = Field(max_length=200)
    old: str = Field(min_length=1, max_length=8000)
    new: str = Field(min_length=1, max_length=8000)


class Repair(BaseModel):
    model_config = ConfigDict(extra='forbid')
    diagnosis: str = Field(min_length=1, max_length=3000)
    edits: list[Edit] = Field(min_length=1, max_length=5)


def source_files(root,globs=None):
    root=root.resolve()
    candidates=set(p for pattern in (globs or ['src/**/*.js']) for p in root.glob(pattern))
    return sorted(p for p in candidates if p.is_file() and not p.is_symlink() and p.resolve().is_relative_to(root) and not any(parent.is_symlink() for parent in p.parents if parent.is_relative_to(root)) and p.suffix in ['.js','.ts','.mjs','.cjs','.tsx','.jsx'] and not any(x in p.name.lower() for x in ['.spec.','.test.','test-','test_']) and not any(x in p.relative_to(root).parts for x in ['node_modules','tests','test','__tests__','.git']))


def digest_files(root: Path, paths) -> str:
    h=hashlib.sha256()
    for p in sorted(paths):
        h.update(str(p.relative_to(root)).encode()+b'\0'+p.read_bytes()+b'\0')
    return h.hexdigest()


def protected_digest(root,globs=None):
    root=root.resolve()
    sources=set(source_files(root,globs))
    return digest_files(root, [p for p in root.rglob('*') if p.is_file() and 'node_modules' not in p.parts and '.git' not in p.parts and p not in sources])


def snapshot_digest(root):
    root=root.resolve()
    return digest_files(root,[p for p in root.rglob('*') if p.is_file() and '.git' not in p.relative_to(root).parts and '.cache' not in p.relative_to(root).parts])


def source_preflight(root,globs=None):
    files=source_files(root,globs)
    if len(files)>500:
        raise ValueError('Source inventory exceeds review limit')
    for p in files:
        if p.stat().st_size>500_000:
            raise ValueError('Source file exceeds review limit: '+str(p.relative_to(root)))
        text=p.read_text()
        if secret_present(text):
            raise ValueError('Possible credential in source; remove it before model processing: '+str(p.relative_to(root)))
    return files


def normalize_bindings(root,repair,globs=None):
    """Preserve an existing local name for a single renamed CommonJS export.

    This is alpha-renaming, not a dependency-specific repair rule. Only complete
    one-line import replacements with an otherwise unused new binding qualify.
    """
    allowed={str(p.relative_to(root)) for p in source_files(root,globs)}
    import_old=re.compile(r"^(\s*)(const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*require\((['\"])([^'\"]+)\4\)\s*;?\s*$")
    import_new=re.compile(r"^(\s*)(const|let|var)\s*\{\s*([A-Za-z_$][\w$]*)\s*\}\s*=\s*require\((['\"])([^'\"]+)\4\)\s*;?\s*$")
    esm_new=re.compile(r"^\s*import\s*\{\s*([A-Za-z_$][\w$]*)\s*\}\s*from\s*(['\"])([^'\"]+)\2\s*;?\s*$")
    edits=[];notes=[]
    for edit in repair.edits:
        old=import_old.fullmatch(edit.old);new=import_new.fullmatch(edit.new)
        replacement=edit.new
        esm=esm_new.fullmatch(edit.new)
        if old and esm and old[5]==esm[3] and edit.path in allowed:
            replacement=f'{old[1]}{old[2]} {{ {esm[1]} }} = require({old[4]}{old[5]}{old[4]})'
            edit=edit.model_copy(update={'new':replacement})
            new=import_new.fullmatch(replacement)
            notes.append(f'{edit.path}: preserved CommonJS module format')
        if old and new and old[5]==new[5] and old[3]!=new[3] and edit.path in allowed:
            content=(root/edit.path).read_text()
            if content.count(edit.old)==1:
                proposed=content
                valid=True
                for candidate in repair.edits:
                    if candidate.path==edit.path:
                        if proposed.count(candidate.old)!=1:valid=False;break
                        proposed=proposed.replace(candidate.old,edit.new if candidate.old==edit.old else candidate.new,1)
                remainder=proposed.replace(edit.new,'',1)
                if valid and re.search(r'\b'+re.escape(old[3])+r'\b',remainder) and not re.search(r'\b'+re.escape(new[3])+r'\b',remainder):
                    replacement=edit.new[:new.start(3)]+new[3]+': '+old[3]+edit.new[new.end(3):]
                    notes.append(f'{edit.path}: preserved local binding {old[3]} for named export {new[3]}')
        if edit.old.endswith('\n') and not replacement.endswith('\n'):replacement+='\n'
        edits.append(edit.model_copy(update={'new':replacement}))
    return repair.model_copy(update={'edits':edits}),notes


def apply_repair(root: Path, repair: Repair, globs=None):
    root=root.resolve()
    allowed={str(p.relative_to(root)) for p in source_files(root,globs)}
    updates={}
    for edit in repair.edits:
        p=PurePosixPath(edit.path)
        if p.is_absolute() or '..' in p.parts or edit.path not in allowed:
            raise ValueError('Edit outside source allowlist')
        path=root/edit.path
        if not path.resolve().is_relative_to(root.resolve()) or path.is_symlink():
            raise ValueError('Symlink edit refused')
        text=updates.get(path,path.read_text())
        if text.count(edit.old)!=1:
            raise ValueError('Edit anchor must occur exactly once')
        if edit.old==edit.new:
            raise ValueError('No-op edit refused')
        for pattern in [r'process\s*\.\s*exit',r'child_process',r'\beval\s*\(',r'new\s+Function',r'\bfetch\s*\(',r'\.\s*(?:skip|only)\s*\(',r'writeFile',r'execSync',r'spawnSync']:
            if len(re.findall(pattern,edit.new))>len(re.findall(pattern,edit.old)):
                raise ValueError('Repair introduces forbidden execution, I/O or test-bypass behavior')
        check_new_capabilities(edit.old,edit.new)
        if secret_present(edit.new):raise ValueError("Repair contains a possible credential")
        updates[path]=text.replace(edit.old,edit.new,1)
    for path,text in updates.items():
        original=path.read_text()
        if len(re.findall(r'\bmodule\.exports\s*=',text))>len(re.findall(r'\bmodule\.exports\s*=',original)):
            raise ValueError('Added module.exports would duplicate or overwrite the existing export; modify the existing implementation in place')
    for p,text in updates.items():
        p.write_text(text)
    return sorted(str(p.relative_to(root)) for p in updates)
