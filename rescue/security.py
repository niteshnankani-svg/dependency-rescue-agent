"""Deterministic tripwires; capability restrictions remain the security boundary."""
import base64
import binascii
from collections import Counter
import json
import os
import re
import unicodedata


class SecurityViolation(RuntimeError):
    """Safe reason code only: never embed the rejected evidence."""


SECRET_PATTERNS = [
    r'gh[pousr]_[A-Za-z0-9]{20,}', r'github_pat_[A-Za-z0-9_]{30,}',
    r'hf_[A-Za-z0-9]{20,}', r'sk-[A-Za-z0-9_-]{20,}',
    r'AIza[0-9A-Za-z_-]{35}', r'AKIA[0-9A-Z]{16}',
    r'-----BEGIN (?:RSA |OPENSSH |EC )?PRIVATE KEY-----',
    r'(?i)(?:api[_-]?key|password|client[_-]?secret|access[_-]?token)\s*[=:]\s*[\"\'][^\"\'\s]{16,}[\"\']',
]
INJECTION_PATTERNS = [
    r'\bforget\s+(?:everything|all)\b.{0,50}\b(?:told|instructions|rules|prompts)\b',
    r'\b(?:act as|pretend (?:to be|you are)|role[- ]?play as|you are now)\b.{0,60}\b(?:system|developer|administrator|unrestricted|unfiltered|jailbroken)\b',
    r'\b(?:new|replacement|real)\s+(?:system|developer)\s+(?:message|prompt|instructions)\b',

    r'\b(?:ignore|disregard|override)\s+(?:(?:all|the|any)\s+)?(?:previous|prior|above|earlier|system|developer)\s+(?:instructions|prompts|rules)',
    r'<\|(?:im_start|im_end|system|assistant|endoftext)\|>|\[/?INST\]|</?(?:system|developer)>',
    r'\b(?:reveal|print|send|exfiltrate|upload)\b.{0,80}\b(?:api keys?|secrets?|credentials?|system prompt|environment variables)\b',
    r'\b(?:disable|bypass|skip)\s+(?:all\s+)?(?:security|guardrails?|approval|verification|tests)\b',
    r'\b(?:ignore|disregard|override|forget|replace|supersede|stop following)\b.{0,100}\b(?:all\s+)?(?:previous|prior|above|earlier|system|developer|safety|security)?\s*(?:instructions?|prompts?|rules?|polic(?:y|ies)|requirements?|constraints?|guardrails?|safeguards?|directives?)\b',
    r'\b(?:obsolete|outdated|superseded|replaced|no longer applies|does not apply)\b.{0,80}\b(?:system|developer|safety|security)?\s*(?:instructions?|prompts?|rules?|polic(?:y|ies)|requirements?|constraints?|guardrails?|safeguards?)\b',
    r'\b(?:do not|don\'t|never)\s+(?:follow|use|obey|enforce)\b.{0,60}\b(?:policy|guardrails?|verification|tests?|approval|safety|security|instructions?)\b',
    r'\b(?:for the rest of this session|from now on|from this point on|starting now|these are the real instructions)\b.{0,120}\b(?:output|print|return|disclose|reveal|dump|ignore|disregard|stop following|mark|declare)\b.{0,100}\b(?:hidden system|developer prompt|secrets?|credentials?|api keys?|environment variables?|tests?|approval|verified|approved)\b',
    r'\b(?:assume|adopt|switch to|enter|take on|pretend to be|role[- ]?play as)\b.{0,60}\b(?:root|admin(?:istrator)?|system|developer|unrestricted|unfiltered|jailbroken)\b.{0,60}\b(?:persona|role|mode|identity)?\b',
    r'\b(?:disclose|dump|return|output|print|expose)\b[^.!?\n]{0,40}\b(?:hidden system|developer prompt|environment variables?|api keys?|secrets?|credentials?|access tokens?)\b',
    r'\b(?:read|retrieve|extract|copy|use|take)\b.{0,80}\b(?:secret|credential|api key|environment variable|access token)\b.{0,100}\b(?:request|http|bearer|external|url|endpoint|post|upload|send|transmit)\b',
    r'\b(?:mark|declare|consider)\b.{0,80}\b(?:patch|repair|change|run|tests?)\b.{0,50}\b(?:approved|verified|safe|passed)\b',
]


def normalized(text):
    text=unicodedata.normalize('NFKC',text)
    # Remove invisible formatting used to split suspicious words.
    return ''.join(c for c in text if unicodedata.category(c)!='Cf')


def secret_present(text):
    if any(re.search(pattern,text) for pattern in SECRET_PATTERNS):return True
    # Also protect configured secrets even when they don't match a known prefix.
    names=['GEMINI_API_KEY','GOOGLE_API_KEY','ANTHROPIC_API_KEY','RESCUE_MODEL_API_KEY','RESCUE_EXECUTOR_TOKEN','RESCUE_API_TOKEN']
    return any(len(value:=os.getenv(name,''))>=16 and value in text for name in names)


def redact_text(text):
    for pattern in SECRET_PATTERNS:text=re.sub(pattern,'[REDACTED]',text)
    for name in ['GEMINI_API_KEY','GOOGLE_API_KEY','ANTHROPIC_API_KEY','RESCUE_MODEL_API_KEY','RESCUE_EXECUTOR_TOKEN','RESCUE_API_TOKEN']:
        value=os.getenv(name,'')
        if len(value)>=16:text=text.replace(value,'[REDACTED]')
    return text


def evidence_variants(text):
    """Bounded heuristic decoding, not an exhaustive encoding/semantic analysis."""
    clean=normalized(text)
    leet=clean.translate(str.maketrans({'0':'o','1':'i','2':'z','3':'e','4':'a','5':'s','6':'g','7':'t','8':'b','9':'g'}))
    variants=[clean,leet]
    remaining=16_384
    frontier=[clean]
    for _ in range(2):
        next_layer=[]
        for current in frontier:
            for match in list(re.finditer(r'(?<![A-Za-z0-9+/])[A-Za-z0-9+/]{24,4096}={0,2}(?![A-Za-z0-9+/=])',current))[:16]:
                token=match[0]
                if len(token)>remaining:continue
                remaining-=len(token)
                try:decoded=base64.b64decode(token,validate=True).decode('utf-8')
                except (ValueError,UnicodeDecodeError,binascii.Error):continue
                decoded=normalized(decoded)
                if not decoded.isprintable() and any(c not in '\n\r\t' and not c.isprintable() for c in decoded):continue
                variants.extend([decoded,decoded.translate(str.maketrans({'0':'o','1':'i','2':'z','3':'e','4':'a','5':'s','6':'g','7':'t','8':'b','9':'g'}))])
                next_layer.append(decoded)
        frontier=next_layer
    return variants


def screen_evidence(value, label='model evidence'):
    text=json.dumps(value,ensure_ascii=False) if not isinstance(value,str) else value
    if len(text)>100_000:raise SecurityViolation('Security policy: evidence budget exceeded')
    if secret_present(text):raise SecurityViolation('Security policy: possible credential in '+label)
    variants=evidence_variants(text)
    if any(secret_present(variant) for variant in variants):raise SecurityViolation('Security policy: possible encoded credential in '+label)
    if any(re.search(pattern,variant,re.I|re.S) for variant in variants for pattern in INJECTION_PATTERNS):
        raise SecurityViolation('Security policy: suspected prompt injection in '+label)
    if any(c in text for c in '\u202a\u202b\u202c\u202d\u202e\u2066\u2067\u2068\u2069'):
        raise SecurityViolation('Security policy: concealed direction controls in '+label)


def screen_output(text):
    if not isinstance(text,str) or len(text)>60_000:
        raise SecurityViolation('Security policy: model output budget exceeded')
    screen_evidence(text,'model output')


def canonical_code(text):
    text=normalized(text)
    text=re.sub(r'\\u([0-9a-fA-F]{4})|\\x([0-9a-fA-F]{2})',lambda m:chr(int(m[1] or m[2],16)),text)
    text=re.sub(r'/\*.*?\*/','',text,flags=re.S)
    text=re.sub(r"['\"]\s*\+\s*['\"]",'',text)
    return text


def check_new_capabilities(old,new):
    old,new=canonical_code(old),canonical_code(new)
    # Fail closed on edited dynamic loaders. We cannot prove variable contents.
    dynamic=r"\b(?:require|import)\s*\((?!\s*['\"])"
    aliases=r"\brequire\b(?!\s*\()"
    if (re.search(dynamic,new) and new!=old) or len(re.findall(aliases,new))>len(re.findall(aliases,old)):
        raise ValueError('Repair introduces or changes a dynamic module loader')
    imports=r"(?:require\s*\(|from\s*|import\s*\()\s*['\"]([^'\"]+)['\"]"
    if set(re.findall(imports,new))-set(re.findall(imports,old)):
        raise ValueError('Repair introduces a new module dependency')
    python_imports=r'(?m)^\s*(?:from\s+([\w.]+)\s+import|import\s+([\w.]+))'
    if set(re.findall(python_imports,new))-set(re.findall(python_imports,old)):
        raise ValueError('Repair introduces a new module dependency')
    patterns=[
        r'\b(?:exec|compile|__import__)\s*\(',
        r'\b(?:subprocess|socket|urllib|requests)\s*\.',
        r'\bos\s*\.\s*(?:system|popen|environ|putenv|remove|unlink|exec\w*|spawn\w*)\b',
        r'\bos\s*\.\s*(?:open|getenv|chmod|chown|listdir|scandir|walk)\b',
        r'\b\w+\s*\.\s*(?:read_text|write_text|read_bytes|write_bytes|unlink|rename|replace|mkdir|rmdir)\s*\(',
        r'\b(?:sys\.exit|shutil\.rmtree|pickle\.loads)\b',
        r'\b(?:axios|superagent|undici)\b',
        r'\b(?:child_process|worker_threads|node:vm)\b',
        r"(?:require\s*\(|from\s*|import\s*\()\s*['\"](?:node:)?(?:fs(?:/promises)?|http2?|https|net|tls|dgram|dns|vm)['\"]",
        r'\b(?:eval|Function|fetch|WebSocket|XMLHttpRequest|execSync|spawnSync|writeFileSync|writeFile)\b',
        r"\bprocess\s*(?:\.\s*|\[\s*['\"])(?:env|exit|binding|mainModule)\b",
        r'\b(?:globalThis|global)\s*\[',
        r'\b(?:atob|fromCharCode)\s*\(',
        r"Buffer\s*\.\s*from\s*\([^\n]*['\"]base64['\"]",
        r'\b(?:rejectUnauthorized\s*:\s*false|NODE_TLS_REJECT_UNAUTHORIZED)\b',
        r'https?://[^\s\"\'`]+',
    ]
    for pattern in patterns:
        before=Counter(re.findall(pattern,old,re.I))
        after=Counter(re.findall(pattern,new,re.I))
        if any(count>before[match] for match,count in after.items()):
            raise ValueError('Repair introduces a forbidden capability or destination')
