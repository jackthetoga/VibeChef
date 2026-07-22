from __future__ import annotations

import uuid

from fastapi import HTTPException
from sqlalchemy import exists, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import CatalogRecipe, Cookbook, Recipe, UploadStatus


async def require_catalog_recipe_access(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    catalog_recipe_id: uuid.UUID,
) -> CatalogRecipe:
    catalog_recipe = await db.get(CatalogRecipe, catalog_recipe_id)
    if catalog_recipe is None:
        raise HTTPException(status_code=404, detail="Catalog recipe not found")

    entitled = await db.scalar(
        select(
            exists(
                select(Recipe.id)
                .join(Cookbook, Cookbook.id == Recipe.cookbook_id)
                .where(
                    Recipe.catalog_recipe_id == catalog_recipe_id,
                    Cookbook.user_id == user_id,
                    Cookbook.status == UploadStatus.completed,
                )
            )
        )
    )
    if not entitled:
        raise HTTPException(status_code=404, detail="Catalog recipe not found")
    return catalog_recipe
