from aiogram import Router
from .core import router as core_router
from .actions import router as actions_router
from .guarantor import router as guarantor_router
from .rating import router as rating_router

router = Router()
router.include_router(core_router)
router.include_router(actions_router)
router.include_router(guarantor_router)
router.include_router(rating_router)
