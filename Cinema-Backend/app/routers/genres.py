from fastapi import APIRouter

from app.dependencies import GenreRepositoryDep
from app.schemas import GenreCatalogOut

router = APIRouter(prefix="/api/genres", tags=["genres"])


@router.get(
    "",
    response_model=list[GenreCatalogOut],
    summary="Жанры",
)
def list_genres(genres: GenreRepositoryDep) -> list[dict]:
    return [
        {
            "id": genre.id,
            "name": genre.name,
            "slug": genre.slug,
            "titles_count": count,
        }
        for genre, count in genres.list_all()
    ]
