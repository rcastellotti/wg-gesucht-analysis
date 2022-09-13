from venv import create
import requests
from bs4 import BeautifulSoup as bs
from dotenv import load_dotenv
import os
import json
from sqlalchemy import (
    create_engine,
    Column,
    Integer,
    String,
    Boolean,
    DateTime,
    ForeignKey,
)
from sqlalchemy_utils import database_exists
import logging
import datetime
from sqlalchemy.orm import declarative_base, relationship, sessionmaker
from mvg_api import *

load_dotenv()
logging.basicConfig(level=logging.INFO)
Base = declarative_base()
engine = create_engine("sqlite:///wg-gesucht-analysis.sqlite", echo=False)
Session = sessionmaker(bind=engine)


def get_lat_lon_distance(location):
    url = "https://nominatim.openstreetmap.org/search.php"

    params = {
        "q": location,
        "format": "jsonv2",
    }

    r = requests.get(url, params=params)
    logging.debug(r.text)
    departure_coordinates = (r.json()[0]["lat"], r.json()[0]["lon"])
    tum_garching_coordinates = ("48.26560225", "11.669936877671844")

    a = get_route(start=departure_coordinates, dest=tum_garching_coordinates)
    arrival_datetime = a[0]["arrival_datetime"]
    departure_datetime = a[0]["departure_datetime"]
    return (
        departure_coordinates[0],
        departure_coordinates[1],
        (arrival_datetime - departure_datetime).total_seconds() / 60,
    )


class Chat(Base):
    __tablename__ = "chat"
    id = Column(Integer, primary_key=True)
    conversation_id = Column(Integer, unique=True)
    location = Column(String)
    size = Column(String)
    type = Column(String)
    lat = Column(String)
    lon = Column(String)
    distance_from_campus = Column(String)
    price = Column(Integer)
    unread = Column(Boolean)
    last_message_time = Column(DateTime, default=datetime.datetime.now)
    last_visited = Column(DateTime, default=datetime.datetime.now)
    messages = relationship("Message", back_populates="chat")

    def __repr__(self):
        return "<Chat(conversation_id='%s')>" % (self.conversation_id,)


class Message(Base):
    __tablename__ = "messages"
    id = Column(Integer, primary_key=True)
    text = Column(String)
    chat_id = Column(Integer, ForeignKey("chat.id"))
    message_number = Column(Integer)
    chat = relationship("Chat")

    def __repr__(self):
        return "<Message for (chat_id='%s')>" % (self.chat_id,)


if not database_exists(engine.url):
    Base.metadata.create_all(engine)


WG_GESUCHT_USERNAME = os.environ["WG_GESUCHT_USERNAME"]
WG_GESUCHT_PASSWORD = os.environ["WG_GESUCHT_PASSWORD"]

s = requests.Session()
r = s.post(
    "https://www.wg-gesucht.de/ajax/sessions.php?action=login",
    json={
        "login_email_username": WG_GESUCHT_USERNAME,
        "login_password": WG_GESUCHT_PASSWORD,
    },
)

r = s.get(
    "https://www.wg-gesucht.de/ajax/conversations.php?action=all-conversations-notifications"
)
convos = json.loads(r.text)["_embedded"]["conversations"]

for convo in convos:
    session = Session()

    chat = Chat(
        conversation_id=convo["conversation_id"],
        last_message_time=datetime.datetime.strptime(
            convo["last_message_timestamp"], "%Y-%m-%d %H:%M:%S"
        ),
        last_visited=datetime.datetime.strptime(
            convo["last_visited"], "%Y-%m-%d %H:%M:%S"
        ),
        unread=bool(convo["unread"]),
    )
    logging.debug(f"adding chat: {chat.conversation_id}")
    session.add(chat)

    a = s.get(
        f"https://www.wg-gesucht.de/nachricht.html?nachrichten-id={chat.conversation_id}"
    )
    soup = bs(a.text, "html.parser")
    try:
        a = (
            soup.find("div", {"class": "sticky_box_content"})
            .find("b")
            .text.replace("\n", "")
            .replace(" ", "")
        )
        location_list = (
            soup.find("div", {"class": "card_body"})
            .find_all("div", {"class": "col-xs-12"})[1]
            .text.strip()
            .replace("\n", "")
            .split("|")
        )
        list = a.split("|")
        chat.type = list[0]
        chat.location = location_list[1]
        chat.lat,chat.lon,chat.distance_from_campus = get_lat_lon_distance(location_list[1])
        chat.size = list[1].replace("m²", "")
        chat.price = list[2].replace("€", "")
    except:
        # ad was removed
        pass
    messages = soup.find_all("div", {"class": "message_text"})
    logging.debug(f"adding messages for chat: {chat.conversation_id}")
    for i, m in enumerate(messages):
        message = Message(text=m.text.strip(), message_number=i)
        message.chat = chat
        session.add(message)
        session.commit()
        # time.sleep(random.randrange(0, 10))
