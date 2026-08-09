"""Mainline Base API Routes"""

def get_health_status():
    return {
        "status": "healthy",
        "service": "paleo-workbench",
        "branch": "main"
    }

def get_system_info():
    return {
        "version": "1.0.0",
        "environment": "production"
    }
