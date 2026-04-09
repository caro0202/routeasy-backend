from fastapi import FastAPI
from pydantic import BaseModel
from fastapi.middleware.cors import CORSMiddleware
import requests
import time
from ortools.constraint_solver import routing_enums_pb2, pywrapcp

app = FastAPI()

# 🔥 CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 🔥 HISTÓRICO EM MEMÓRIA
history_storage = []

API_KEY = "eyJvcmciOiI1YjNjZTM1OTc4NTExMTAwMDFjZjYyNDgiLCJpZCI6IjNjODEyOTY3MzJjNzRmZGY5OWEzN2YwZGY2MjJkZWM0IiwiaCI6Im11cm11cjY0In0="

class RouteRequest(BaseModel):
    addresses: list = []
    coords: list = []

# -------------------------
# UTILIDADES
# -------------------------

def clean_address(addr):
    return addr.replace(",", " ").strip()

def get_coordinates(address):
    url = "https://nominatim.openstreetmap.org/search"
    params = {"q": address, "format": "json", "limit": 1}
    headers = {"User-Agent": "route-optimizer"}

    try:
        r = requests.get(url, params=params, headers=headers)
        if r.status_code == 200 and r.json():
            data = r.json()[0]
            return [float(data["lon"]), float(data["lat"])]
    except:
        pass

    return None

def get_matrix(coords):
    url = "https://api.openrouteservice.org/v2/matrix/driving-car"
    headers = {
        "Authorization": API_KEY,
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
        "Authorization": API_KEY,
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

    addresses = data.addresses or []
    coords_input = data.coords or []

    valid_coords = []
    valid_labels = []
    invalid_addresses = []

    # 🔥 geocoding
    if coords_input and len(coords_input) >= 2:
        valid_coords = coords_input
        valid_labels = [f"Ponto {i+1}" for i in range(len(coords_input))]
    else:
        for addr in addresses:
            cleaned = clean_address(addr)
            coord = get_coordinates(cleaned)

            if coord:
                valid_coords.append(coord)
                valid_labels.append(addr)
            else:
                invalid_addresses.append(addr)

            time.sleep(1)

    if len(valid_coords) < 2:
        return {
            "route": [],
            "invalidAddresses": invalid_addresses,
            "totalDistance": 0,
            "estimatedDuration": 0
        }

    # 🔥 matriz
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
            "stopIndex": i,
            "distanceToNext": None
        }
        for i in range(len(optimized_coords))
    ]

    result = {
        "route": formatted_route,
        "invalidAddresses": invalid_addresses,
        "totalDistance": route["summary"]["distance"] / 1000,
        "estimatedDuration": route["summary"]["duration"] / 60
    }

    return result

# -------------------------
# HISTÓRICO
# -------------------------

@app.post("/save-history")
def save_history(data: dict):
    history_storage.append(data)
    return {"status": "ok"}

@app.get("/history")
def get_history():
    return history_storage