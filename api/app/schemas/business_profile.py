"""Structured business knowledge for voice agents (Phase B)."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class ProfileSource(BaseModel):
    url: str = ""
    page: str = ""
    field: str = ""


class BusinessInfo(BaseModel):
    name: str = ""
    type: Literal[
        "resort",
        "real_estate",
        "college",
        "retail",
        "clinic",
        "other",
    ] = "other"
    one_line_pitch: str = ""


class DistanceFrom(BaseModel):
    place: str = ""
    km: float | None = None
    drive_time: str = ""


class LocationInfo(BaseModel):
    full_address: str = ""
    area: str = ""
    city: str = ""
    state: str = ""
    landmarks: list[str] = Field(default_factory=list)
    directions: list[str] = Field(default_factory=list)
    distance_from: list[DistanceFrom] = Field(default_factory=list)
    maps_link: str = ""


class ContactInfo(BaseModel):
    reception_phone: str = ""
    whatsapp: str = ""
    email: str = ""
    hours: str = ""


class Offering(BaseModel):
    name: str = ""
    description: str = ""
    capacity: str = ""
    price_from: float | None = None
    price_unit: str = ""
    price_notes: str = ""


class OfferItem(BaseModel):
    text: str = ""
    valid_till: str = ""


class FaqItem(BaseModel):
    q: str = ""
    a: str = ""


class ObjectionItem(BaseModel):
    objection: str = ""
    response_facts: str = ""


class PolicyInfo(BaseModel):
    check_in: str = ""
    check_out: str = ""
    cancellation: str = ""
    advance_payment: str = ""
    id_required: str = ""
    pets: str = ""
    outside_food: str = ""


class Persona(BaseModel):
    name: str = ""
    gender: str = ""
    voice: str = ""
    languages: list[str] = Field(default_factory=list)


class BusinessProfile(BaseModel):
    business: BusinessInfo = Field(default_factory=BusinessInfo)
    location: LocationInfo = Field(default_factory=LocationInfo)
    contact: ContactInfo = Field(default_factory=ContactInfo)
    offerings: list[Offering] = Field(default_factory=list)
    amenities: list[str] = Field(default_factory=list)
    policies: PolicyInfo = Field(default_factory=PolicyInfo)
    offers: list[OfferItem] = Field(default_factory=list)
    usps: list[str] = Field(default_factory=list)
    faqs: list[FaqItem] = Field(default_factory=list)
    objection_handling: list[ObjectionItem] = Field(default_factory=list)
    unknown_policy: str = "callback"
    sources: list[ProfileSource] = Field(default_factory=list)
    profile_version: int = 1

    @classmethod
    def from_snapshot(cls, raw: dict[str, Any] | None) -> BusinessProfile:
        if not raw:
            return cls()
        try:
            return cls.model_validate(raw)
        except Exception:
            return cls()

    def warnings(self) -> list[str]:
        w: list[str] = []
        if not self.location.full_address and not self.location.area:
            w.append("No location — callers asking where you are will get a callback offer.")
        if not self.contact.reception_phone:
            w.append("No reception phone — office-number questions cannot be answered from facts.")
        if not any(o.price_from for o in self.offerings):
            w.append("No prices in profile — price questions need callback or dates for availability.")
        return w