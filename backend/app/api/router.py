from fastapi import APIRouter

from app.api.routes.auth import router as auth_router
from app.api.routes.cookbooks import router as cookbook_router
from app.api.routes.pantry import ingredient_router, pantry_router
from app.api.routes.recipes import router as recipe_router
from app.api.routes.reviews import router as reviews_router

api_router = APIRouter()
api_router.include_router(auth_router)
api_router.include_router(cookbook_router)
api_router.include_router(ingredient_router)
api_router.include_router(pantry_router)
api_router.include_router(recipe_router)
api_router.include_router(reviews_router)
