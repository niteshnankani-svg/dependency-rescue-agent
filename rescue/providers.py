"""Hosted provider configuration. Credentials never enter prompts or run reports."""
import os
from urllib.parse import urlsplit


def settings():
    provider=os.getenv('RESCUE_MODEL_PROVIDER','ollama')
    defaults={
        'ollama':('http://127.0.0.1:11434','qwen3:4b'),
        'gemini':('https://generativelanguage.googleapis.com/v1beta','gemini-3.1-pro-preview'),
        'anthropic':('https://api.anthropic.com/v1','claude-sonnet-4-6'),
        'chat-completions':('', ''),
    }
    if provider not in defaults:raise ValueError('Unsupported model provider')
    url,model=defaults[provider]
    key=os.getenv('RESCUE_MODEL_API_KEY') or os.getenv({'gemini':'GEMINI_API_KEY','anthropic':'ANTHROPIC_API_KEY'}.get(provider,'RESCUE_MODEL_API_KEY'))
    if provider=='gemini':key=key or os.getenv('GOOGLE_API_KEY')
    url=os.getenv('RESCUE_MODEL_URL') or url
    parsed=urlsplit(url)
    if parsed.username or parsed.password or parsed.query or parsed.fragment:raise ValueError('Model URL must not contain credentials, query or fragment')
    hosts={'gemini':'generativelanguage.googleapis.com','anthropic':'api.anthropic.com'}
    if provider in hosts and (parsed.scheme!='https' or parsed.hostname!=hosts[provider] or parsed.port not in [None,443]):
        raise ValueError('Native hosted provider requires its official HTTPS endpoint')
    if os.getenv('RESCUE_ENV')=='production' and provider=='chat-completions' and parsed.scheme!='https':
        raise ValueError('Production compatible providers require HTTPS')
    return provider,url,os.getenv('RESCUE_MODEL') or model,key


def model_trust_env():
    """Operator opt-in for model transport proxies and custom CA certificates."""
    return os.getenv('RESCUE_MODEL_TRUST_ENV')=='1'
