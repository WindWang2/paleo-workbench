"""Mainline Unit Tests"""
from src.api.routes import get_health_status, get_system_info

def test_health():
    res = get_health_status()
    assert res["status"] == "healthy"
    assert res["branch"] == "main"

def test_system_info():
    info = get_system_info()
    assert info["version"] == "1.0.0"
