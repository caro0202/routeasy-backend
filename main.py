from fastapi import FastAPI
from pydantic import BaseModel
from fastapi.middleware.cors import CORSMiddleware
import requests
import time
from ortools.constraint_solver import routing_enums_pb2, pywrapcp

# 🔥 NOVO (BANCO)
from sqlalchemy import create_engine, Column, Integer, String
from sqlalchemy.orm import sessionmaker, declarative_base

# 🔥 DATABASE
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

API_KEY = "eyJvcmciOiI1YjNjZTM1OTc4NTExMTAwMDFjZjYyNDgi"

class RouteRequest(BaseModel):
    addresses: list = []
    coords: list = []

# -------------------------
# 🔥 MODELO DO BANCO
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

    # 🔥 normalização forte
    addr = addr.replace("r ", "rua ")
    addr = addr.replace("av ", "avenida ")
    addr = addr.replace(",", " ")
    addr = addr.replace(".", " ")
    addr = addr.replace("-", " ")
    addr = addr.replace("  ", " ")

    # 🔥 força contexto correto
    if "itatiba" not in addr:
        addr += " itatiba"

    if "sao paulo" not in addr:
        addr += " sao paulo"

    if "brasil" not in addr:
        addr += " brasil"

    return addr.strip()

def get_coordinates(address):
    url = "https://nominatim.openstreetmap.org/search"
    params = {"q": address, "format": "json", "limit": 1}
    headers = {"User-Agent": "route-optimizer"}

    try:
        print("🔎 Buscando:", address)

        r = requests.get(url, params=params, headers=headers)

        if r.status_code == 200 and r.json():
            data = r.json()[0]
            coord = [float(data["lon"]), float(data["lat"])]
            print("✅ Encontrado:", coord)
            return coord

        print("❌ Não encontrado:", address)

    except Exception as e:
        print("⚠️ Erro geocoding:", e)

    return None

def get_matrix(coords):
    url = "https://api.openrouteservice.org/v2/matrix/driving-car"
    headers = {"Authorization": API_KEY, "Content-Type": "application/json"}

    body = {
        "locations": coords,
        "metrics": ["distance", "duration"]
    }

    r = requests.post(url, json=body, headers=headers)

    if r.status_code == 200:
        data = r.json()
        return data["distances"], data["durations"]

    print("❌ Erro matrix:", r.text)
    return None, None

def get_route(coords):
    url = "https://api.openrouteservice.org/v2/directions/driving-car"
    headers = {"Authorization": API_KEY, "Content-Type": "application/json"}

    body = {"coordinates": coords}

    r = requests.post(url, json=body, headers=headers)

    if r.status_code == 200:
        return r.json()

    print("❌ Erro route:", r.text)
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

        time.sleep(1)

    print("📍 Coordenadas válidas:", valid_coords)
    print("⚠️ Inválidos:", invalid_addresses)

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

    # 🔥 salvar histórico
    db.add(History(input=str(data.addresses)))
    db.commit()

    result = {
        "route": formatted_route,
        "invalidAddresses": invalid_addresses,
        "totalDistance": route["summary"]["distance"] / 1000,
        "estimatedDuration": route["summary"]["duration"] / 60
    }

    print("🚀 Resultado final:", result)

    return result

# -------------------------
# HISTÓRICO
# -------------------------

@app.get("/history")
def get_history():
    db = SessionLocal()
    items = db.query(History).all()
    return [{"input": i.input} for i in items]