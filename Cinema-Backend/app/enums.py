from enum import StrEnum

MIN_YEAR = 1888
MAX_YEAR = 2200


class TitleType(StrEnum):
    MOVIE = "movie"
    SERIES = "series"


class TitleSort(StrEnum):
    ID_DESC = "-id"
    ID_ASC = "id"
    NAME_ASC = "name"
    NAME_DESC = "-name"
    YEAR_ASC = "year"
    YEAR_DESC = "-year"
    CREATED_DESC = "-created_at"
    CREATED_ASC = "created_at"
