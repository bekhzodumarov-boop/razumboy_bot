from .common import router as common_router
from .registration import router as registration_router
from .admin import router as admin_router
from .user import router as user_router

__all__ = ["common_router", "registration_router", "admin_router", "user_router"]
