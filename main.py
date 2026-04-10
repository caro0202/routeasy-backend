from fastapi import FastAPI
from pydantic import BaseModel
from fastapi.middleware.cors import CORSMiddleware
import requests
import time
from ortools.constraint_solver import routing_enums_pb2, pywrapcp

# 🔥 BANCO
from sqlalchemy import create_engine, Column, Integer, String
from sqlalchemy.orm import sessionmaker, declarative_base

DATABASE_URL = "postgresql+psycopg2://routeasy_user:ctvMqrVrVdTAmoheJP2NJZ5KGxn6tv8J@dpg-d7c27l67r5hc739l5nng-a.oregon-postgres.render.com/routeasy"

engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(bind=engine)
Base = declarative_base()

app = FastAPI()

# 🔥 CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 🔥 API KEYS
GOOGLE_API_KEY = "AIzaSyCDNZNm7Hy3wUWTqL2CDfKgMze8Q_P5CBk"
ORS_API_KEY = "eyJvcmciOiI1YjNjZTM1OTc4NTExMTAwMDFjZjYyNDgi"

class RouteRequest(BaseModel):
    addresses: list = []

# -------------------------
# BANCO
# -------------------------

class History(Base):
    __tablename__ = "history"
    id = Column(Integer, primary_key=True)
    input = Column(String)

Base.metadata.create_all(bind=engine)

# -------------------------
# UTILIDADES
# -------------------------

def clean_address(addr):
    addr = addr.lower()

    addr = addr.replace("r ", "rua ")
    addr = addr.replace("av ", "avenida ")
    addr = addr.replace(",", " ")
    addr = addr.replace(".", " ")
    addr = addr.replace("-", " ")
    addr = addr.replace("  ", " ")

    return addr.strip()

# 🔥 GEOCODING COM FALLBACK REAL
def get_coordinates(address):

    # 1️⃣ GOOGLE
    try:
        url = "https://maps.googleapis.com/maps/api/geocode/json"

        params = {
            "address": address,
            "key": GOOGLE_API_KEY
        }

        r = requests.get(url, params=params)
        data = r.json()

        print("🔎 Google:", data.get("status"))

        if data["status"] == "OK" and data["results"]:
            loc = data["results"][0]["geometry"]["location"]
            return [loc["lng"], loc["lat"]]

    except Exception as e:
        print("⚠️ Erro Google:", e)

    # 2️⃣ FALLBACK ORS
    try:
        url = "https://api.openrouteservice.org/geocode/search"
        headers = {"Authorization": ORS_API_KEY}
        params = {"text": address, "size": 1}

        r = requests.get(url, params=params, headers=headers)
        data = r.json()

        print("🔎 ORS fallback")

        if "features" in data and data["features"]:
            coords = data["features"][0]["geometry"]["coordinates"]
            return coords

    except Exception as e:
        print("⚠️ Erro ORS:", e)

    print("❌ Endereço inválido:", address)
    return None

def get_matrix(coords):
    url = "https://api.openrouteservice.org/v2/matrix/driving-car"
    headers = {
        "Authorization": ORS_API_KEY,
        "Content-Type": "application/json"
    }

    body = {
        "locations": coords,
        "metrics": ["distance", "duration"]
    }

    r = requests.post(url, json=body, headers=headers)

    if r.status_code == 200:
        data = r.json()
        return data["distances"], data["durations"]

    return None, None

def get_route(coords):
    url = "https://api.openrouteservice.org/v2/directions/driving-car"
    headers = {
        "Authorization": ORS_API_KEY,
        "Content-Type": "application/json"
    }

    body = {"coordinates": coords}

    r = requests.post(url, json=body, headers=headers)

    if r.status_code == 200:
        return r.json()

    return None

# -------------------------
# API PRINCIPAL
# -------------------------

@app.post("/optimize")
def optimize(data: RouteRequest):

    db = SessionLocal()

    valid_coords = []
    valid_labels = []
    invalid_addresses = []

    for addr in data.addresses:
        cleaned = clean_address(addr)
        coord = get_coordinates(cleaned)

        if coord:
            valid_coords.append(coord)
            valid_labels.append(addr)
        else:
            invalid_addresses.append(addr)

        time.sleep(0.2)

    if len(valid_coords) < 2:
        return {
            "route": [],
            "invalidAddresses": invalid_addresses,
            "totalDistance": 0,
            "estimatedDuration": 0
        }

    dist_matrix, dur_matrix = get_matrix(valid_coords)

    if not dist_matrix:
        return {
            "route": [],
            "invalidAddresses": invalid_addresses,
            "totalDistance": 0,
            "estimatedDuration": 0
        }

    manager = pywrapcp.RoutingIndexManager(len(valid_coords), 1, 0)
    routing = pywrapcp.RoutingModel(manager)

    def callback(from_index, to_index):
        return int(dist_matrix[
            manager.IndexToNode(from_index)
        ][
            manager.IndexToNode(to_index)
        ])

    transit_index = routing.RegisterTransitCallback(callback)
    routing.SetArcCostEvaluatorOfAllVehicles(transit_index)

    search = pywrapcp.DefaultRoutingSearchParameters()
    search.first_solution_strategy = routing_enums_pb2.FirstSolutionStrategy.PATH_CHEAPEST_ARC

    solution = routing.SolveWithParameters(search)

    order = []
    index = routing.Start(0)

    while not routing.IsEnd(index):
        node = manager.IndexToNode(index)
        order.append(node)
        index = solution.Value(routing.NextVar(index))

    optimized_coords = [valid_coords[i] for i in order]
    optimized_labels = [valid_labels[i] for i in order]

    route_data = get_route(optimized_coords)

    if not route_data:
        return {
            "route": [],
            "invalidAddresses": invalid_addresses,
            "totalDistance": 0,
            "estimatedDuration": 0
        }

    route = route_data["routes"][0]

    formatted_route = [
        {
            "address": optimized_labels[i],
            "lat": optimized_coords[i][1],
            "lng": optimized_coords[i][0],
        }
        for i in range(len(optimized_coords))
    ]

    db.add(History(input=str(data.addresses)))
    db.commit()

    return {
        "route": formatted_route,
        "invalidAddresses": invalid_addresses,
        "totalDistance": route["summary"]["distance"] / 1000,
        "estimatedDuration": route["summary"]["duration"] / 60
    }

# -------------------------
# HISTÓRICO
# -------------------------

@app.get("/history")
def get_history():
    db = SessionLocal()
    items = db.query(History).all()
    return [{"input": i.input} for i in items]