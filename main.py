from fastapi import FastAPI
from pydantic import BaseModel
from fastapi.middleware.cors import CORSMiddleware
import requests

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

ORS_API_KEY = "eyJvcmciOiI1YjNjZTM1OTc4NTExMTAwMDFjZjYyNDgi"

class RouteRequest(BaseModel):
    addresses: list = []

@app.post("/optimize")
def optimize(data: RouteRequest):

    # 🔥 CONVERTE ENDEREÇOS DIRETO COM ORS
    coords = []

    for addr in data.addresses:
        geo_url = "https://api.openrouteservice.org/geocode/search"
        headers = {"Authorization": ORS_API_KEY}
        params = {"text": addr, "size": 1}

        r = requests.get(geo_url, params=params, headers=headers)
        geo_data = r.json()

        if geo_data.get("features"):
            coords.append(geo_data["features"][0]["geometry"]["coordinates"])

    if len(coords) < 2:
        return {
            "route": [],
            "invalidAddresses": data.addresses,
            "totalDistance": 0,
            "estimatedDuration": 0
        }

    # 🔥 ROTA DIRETA
    route_url = "https://api.openrouteservice.org/v2/directions/driving-car"
    headers = {
        "Authorization": ORS_API_KEY,
        "Content-Type": "application/json"
    }

    body = {
        "coordinates": coords
    }

    r = requests.post(route_url, json=body, headers=headers)

    if r.status_code != 200:
        return {
            "route": [],
            "invalidAddresses": data.addresses,
            "totalDistance": 0,
            "estimatedDuration": 0
        }

    data = r.json()
    route = data["routes"][0]

    formatted_route = [
        {
            "lat": coord[1],
            "lng": coord[0]
        }
        for coord in coords
    ]

    return {
        "route": formatted_route,
        "invalidAddresses": [],
        "totalDistance": route["summary"]["distance"] / 1000,
        "estimatedDuration": route["summary"]["duration"] / 60
    }