from datetime import date, time

from pydantic import BaseModel, EmailStr, Field, model_validator


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=255)

    @model_validator(mode="after")
    def normalize(self):
        self.email = self.email.lower().strip()
        return self


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
    def clean_and_check(self):
        self.subject = self.subject.strip()
        self.faculty = self.faculty.strip()
        if not self.subject or not self.faculty:
            raise ValueError("Subject and faculty can't be blank.")
        if self.start_time >= self.end_time:
            raise ValueError("Start time must be before end time.")
        return self


class StudentCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    email: EmailStr
    password: str = Field(min_length=6, max_length=255)

    @model_validator(mode="after")
    def normalize(self):
        self.name = self.name.strip()
        self.email = self.email.lower().strip()
        if not self.name:
            raise ValueError("Name can't be blank.")
        return self
