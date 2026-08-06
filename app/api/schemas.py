from datetime import date, time

from pydantic import BaseModel, Field, model_validator


class LoginRequest(BaseModel):
    email: str = Field(min_length=3, max_length=190)
    password: str = Field(min_length=1, max_length=255)


class TokenResponse(BaseModel):
    token: str
    user: dict


class SessionCreateRequest(BaseModel):
    subject: str = Field(min_length=1, max_length=120)
    faculty: str = Field(min_length=1, max_length=120)
    date: date
    start_time: time
    end_time: time
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    radius_meters: int = Field(gt=0, le=5000, default=75)
    qr_expiry_minutes: int = Field(gt=0, le=1440, default=3)

    @model_validator(mode="after")
    def check_times(self):
        if self.start_time >= self.end_time:
            raise ValueError("start_time must be before end_time")
        return self


class ScanRequest(BaseModel):
    session_id: int
    qr_token: str = Field(min_length=1, max_length=128)
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
