"""Validation: pages checked against the data model, and the recipe stamped on every step."""
from linecaster.components.validation.page_validator import PageValidator
from linecaster.components.validation.recipe_stamper import RecipeStamper

__all__ = ["RecipeStamper", "PageValidator"]
