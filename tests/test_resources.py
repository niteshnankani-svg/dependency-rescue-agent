import pytest
from rescue import resources


def test_development_scheduler_restores_worker_after_model_failure(monkeypatch):
    calls=[]
    monkeypatch.setenv('RESCUE_SERIAL_COLIMA','rescue')
    monkeypatch.setenv('RESCUE_DOCKER_CONTEXT','colima-rescue')
    monkeypatch.setattr(resources.sys,'platform','darwin')
    monkeypatch.setattr(resources.subprocess,'run',lambda args,**kwargs:calls.append(args))
    with pytest.raises(ValueError):
        with resources.model_resources('code-model'):raise ValueError('model failed')
    assert calls[0]==['colima','stop','rescue']
    assert calls[-1][:3]==['colima','start','rescue']


def test_serial_scheduler_refuses_production(monkeypatch):
    monkeypatch.setenv('RESCUE_SERIAL_COLIMA','rescue')
    monkeypatch.setenv('RESCUE_ENV','production')
    with pytest.raises(RuntimeError,match='development'):
        with resources.model_resources('code-model'):pass
