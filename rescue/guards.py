import hashlib
from pathlib import Path, PurePosixPath
from pydantic import BaseModel, ConfigDict, Field


class Edit(BaseModel):
    model_config = ConfigDict(extra='forbid')
    path: str = Field(max_length=200)
    old: str = Field(min_length=1, max_length=8000)
    new: str = Field(min_length=1, max_length=8000)


class Repair(BaseModel):
    model_config = ConfigDict(extra='forbid')
    diagnosis: str = Field(min_length=1, max_length=3000)
    edits: list[Edit] = Field(min_length=1, max_length=1)


def source_files(root):
    root=root.resolve()
    return sorted(p for p in (root/'src').rglob('*.js') if not p.is_symlink() and p.resolve().is_relative_to(root) and not any(parent.is_symlink() for parent in p.parents if parent.is_relative_to(root)) and '.spec.' not in p.name and 'test' not in p.name.lower())


def digest_files(root: Path, paths) -> str:
    h=hashlib.sha256()
    for p in sorted(paths):
        h.update(str(p.relative_to(root)).encode()+b'\0'+p.read_bytes()+b'\0')
    return h.hexdigest()


def protected_digest(root):
    return digest_files(root, [p for p in root.rglob('*') if p.is_file() and 'node_modules' not in p.parts and '.git' not in p.parts and p not in source_files(root)])


def apply_repair(root: Path, repair: Repair):
    allowed={str(p.relative_to(root)) for p in source_files(root)}
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
        updates[path]=text.replace(edit.old,edit.new,1)
    for p,text in updates.items():
        p.write_text(text)
    return sorted(str(p.relative_to(root)) for p in updates)
