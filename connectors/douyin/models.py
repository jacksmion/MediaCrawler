from pydantic import BaseModel, Field


class VideoUrlInfo(BaseModel):
    aweme_id: str = Field(title="aweme id (video id)")
    url_type: str = Field(default="normal", title="url type: normal, short, modal")


class CreatorUrlInfo(BaseModel):
    sec_user_id: str = Field(title="sec_user_id (creator id)")
