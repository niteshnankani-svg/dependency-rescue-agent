"""Deterministic tripwires; capability restrictions remain the security boundary."""
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
    r'\b(?:ignore|disregard|override)\s+(?:(?:all|the|any)\s+)?(?:previous|prior|above|earlier|system|developer)\s+(?:instructions|prompts|rules)',
    r'<\|(?:im_start|im_end|system|assistant|endoftext)\|>|\[/?INST\]|</?(?:system|developer)>',
    r'\b(?:reveal|print|send|exfiltrate|upload)\b.{0,80}\b(?:api keys?|secrets?|credentials?|system prompt|environment variables)\b',
    r'\b(?:disable|bypass|skip)\s+(?:all\s+)?(?:security|guardrails?|approval|verification|tests)\b',
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


def screen_evidence(value, label='model evidence'):
    text=json.dumps(value,ensure_ascii=False) if not isinstance(value,str) else value
    if len(text)>100_000:raise SecurityViolation('Security policy: evidence budget exceeded')
    if secret_present(text):raise SecurityViolation('Security policy: possible credential in '+label)
    clean=normalized(text)
    if any(re.search(pattern,clean,re.I|re.S) for pattern in INJECTION_PATTERNS):
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
    imports=r"(?:require\s*\(|from\s*|import\s*\()\s*['\"]([^'\"]+)['\"]"
    if set(re.findall(imports,new))-set(re.findall(imports,old)):
        raise ValueError('Repair introduces a new module dependency')
    patterns=[
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
        before=set(re.findall(pattern,old,re.I))
        if any(match not in before for match in re.findall(pattern,new,re.I)):
            raise ValueError('Repair introduces a forbidden capability or destination')
