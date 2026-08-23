"""Public therapist profiles imported from the existing Equal SPA PDF catalog."""

from __future__ import annotations

import os
from typing import NamedTuple


class TherapistProfile(NamedTuple):
    name: str
    slug: str
    category: str
    height: str
    weight: str


THERAPIST_PROFILES = (
    TherapistProfile("Eason", "eason", "straight", "180", "72"),
    TherapistProfile("Show", "show", "straight", "187", "82"),
    TherapistProfile("霍爾", "hol", "straight", "174", "63"),
    TherapistProfile("小六", "xiaoliu", "straight", "170", "60"),
    TherapistProfile("吳樂", "wule", "straight", "173", "75"),
    TherapistProfile("小馬", "xiaoma", "straight", "180", "75"),
    TherapistProfile("Frank", "frank", "straight", "178", "70"),
    TherapistProfile("捷程", "jiecheng", "straight", "175", "82"),
    TherapistProfile("Jun", "jun", "straight", "176", "76"),
    TherapistProfile("小猴", "xiaohou", "straight", "175", "69"),
    TherapistProfile("小虎", "xiaohu", "straight", "182", "79"),
    TherapistProfile("白羊", "baiyang", "straight", "170", "52"),
    TherapistProfile("佐恩", "zuoen", "straight", "178", "60"),
    TherapistProfile("宇森", "yusen", "straight", "180", "84"),
    TherapistProfile("Harry", "harry", "gay", "170", "56"),
    TherapistProfile("士羽", "shiyu", "gay", "172", "73"),
    TherapistProfile("瑞奇", "ricky", "gay", "172", "56"),
    TherapistProfile("朗", "lang", "gay", "185", "81"),
    TherapistProfile("Jack", "jack", "gay", "167", "58"),
    TherapistProfile("Max", "max", "gay", "176", "70"),
    TherapistProfile("泠", "ling", "gay", "173", "65"),
    TherapistProfile("阿焰", "ayan", "gay", "177", "65"),
    TherapistProfile("Jacob", "jacob", "gay", "185", "80"),
    TherapistProfile("華", "hua", "gay", "177", "68"),
    TherapistProfile("武", "wu", "gay", "174", "72"),
    TherapistProfile("Seven", "seven", "gay", "177", "67"),
    TherapistProfile("小柏", "xiaobai", "gay", "175", "78"),
    TherapistProfile("Wilson", "wilson", "gay", "177", "77"),
    TherapistProfile("Wayne", "wayne", "gay", "178", "70"),
    TherapistProfile("路卡", "luka", "gay", "157", "56"),
    TherapistProfile("Erik", "erik", "gay", "163", "53"),
    TherapistProfile("Mars", "mars", "gay", "175", "80"),
    TherapistProfile("ED", "ed", "gay", "178", "71"),
    TherapistProfile("萊伊", "lai", "gay", "185", "75"),
    TherapistProfile("Alex", "alex", "gay", "180", "74"),
    TherapistProfile("Fali", "fali", "gay", "180", "64"),
    TherapistProfile("伊恩", "ian", "gay", "169", "58"),
    TherapistProfile("Zane", "zane", "gay", "174", "70"),
    TherapistProfile("Eden", "eden", "gay", "173", "70"),
    TherapistProfile("沐恩", "muen", "bisexual", "172", "66"),
    TherapistProfile("阿玄", "axuan", "bisexual", "175", "59"),
    TherapistProfile("尼爾", "neil", "bisexual", "178", "75"),
    TherapistProfile("彥", "yan", "bisexual", "175", "79"),
    TherapistProfile("承承", "chengcheng", "bisexual", "170", "55"),
    TherapistProfile("小安", "xiaoan", "bisexual", "173", "58"),
    TherapistProfile("小羅", "xiaoluo", "bisexual", "183", "68"),
    TherapistProfile("可樂", "kele", "bisexual", "170", "60"),
)


def therapist_photo_url(profile: TherapistProfile) -> str:
    base = os.getenv(
        "THERAPIST_IMAGE_BASE_URL",
        "https://raw.githubusercontent.com/nimotherb/linebot/main/official-website/public/images/therapists",
    ).rstrip("/")
    public_category = "community" if profile.category == "gay" else profile.category
    return f"{base}/{public_category}/{profile.slug}.png"
