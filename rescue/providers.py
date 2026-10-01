"""Hosted provider configuration. Credentials never enter prompts or run reports."""
import os


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
    return provider,os.getenv('RESCUE_MODEL_URL') or url,os.getenv('RESCUE_MODEL') or model,key
