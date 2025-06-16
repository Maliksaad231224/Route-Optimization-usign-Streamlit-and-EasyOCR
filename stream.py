import streamlit as st
import os
from typing import List 
from supabase import create_client
import logging
import requests
from supabase.lib.client_options import ClientOptions
import easyocr
import warnings

# Suppress specific warnings
warnings.filterwarnings("ignore", category=UserWarning, message=".*pin_memory.*")
DEPOTS = [
    "7300 N Silverbell Rd, Tucson, AZ",
    "775 W Silverlake Rd, Tucson, AZ",
    "3780 E Valencia Rd, Tucson, AZ"
]

def verify_user(username: str, password: str) -> bool:
    try:
        # Hardcoded credentials (for development only)
        CREDENTIALS = {
            "delieveryuser": "securepass123"
        }
        
        if username in CREDENTIALS and password == CREDENTIALS[username]:
            return True
        return False
    except Exception as e:
        logger.error(f"Authentication error: {str(e)}")
        return False
    
# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Initialize EasyOCR reader in a Streamlit-friendly way
@st.cache_resource
def init_ocr_reader():
    try:
        # Initialize with the lightest settings
        return easyocr.Reader(
            ['en'], 
            gpu=False,
            model_storage_directory='easyocr_models',
            download_enabled=True
        )
    except Exception as e:
        logger.error(f"Failed to initialize EasyOCR: {str(e)}")
        return None

reader = init_ocr_reader()

# Modified init_config function
@st.cache_resource
def init_config():
    config = {
        "SUPABASE_URL": "https://oeuhdztwdrrsbutfebtx.supabase.co",
        "SUPABASE_ANON_KEY": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Im9ldWhkenR3ZHJyc2J1dGZlYnR4Iiwicm9sZSI6ImFub24iLCJpYXQiOjE3NDk1OTkwNjIsImV4cCI6MjA2NTE3NTA2Mn0.6UAaePh9HUo6WpG1VxsTCR4EjPVdJnmxhOt74PU10Ic",
        "ORS_API_KEY": None,
        "GOOGLE_MAPS_API_KEY": None,
        "SUPABASE_PASS": None,
        "SUPABASE": None
    }

    try:
        if hasattr(st, 'secrets'):
            config.update({
                "ORS_API_KEY": st.secrets.get("ORS_API_KEY"),
                "GOOGLE_MAPS_API_KEY": st.secrets.get("GOOGLE_MAPS_API_KEY"),
                "SUPABASE_PASS": st.secrets.get("SUPABASE_PASS")
            })
    except Exception as e:
        logger.error(f"Error loading secrets: {str(e)}")

    # Initialize Supabase
    try:
        if config["SUPABASE_URL"] and config["SUPABASE_ANON_KEY"]:
            client_options = ClientOptions(
                postgrest_client_timeout=10,
                auto_refresh_token=False,
                persist_session=False
            )
            
            config["SUPABASE"] = create_client(
                supabase_url=config["SUPABASE_URL"],
                supabase_key=config["SUPABASE_ANON_KEY"],
                options=client_options
            )
            
            # Test connection
            try:
                result = config["SUPABASE"].from_("gate_codes").select("*").limit(1).execute()
                logger.info("Supabase connection test successful")
            except Exception as test_error:
                logger.error(f"Supabase test query failed: {str(test_error)}")
                config["SUPABASE"] = None
        else:
            logger.warning("Supabase credentials missing")
            config["SUPABASE"] = None
    except Exception as e:
        logger.error(f"Supabase initialization error: {str(e)}")
        config["SUPABASE"] = None
    
    return config

config = init_config()

# Improved OCR Processing
def process_image(image_bytes):
    if not reader:
        return ["OCR engine not initialized"]
        
    try:
        # Use detail=0 for faster processing with less detail
        results = reader.readtext(image_bytes, detail=0, paragraph=True)
        
        if not results:
            return ["No text detected"]

        logger.info(f'Raw OCR results: {results}')
        
        # Improved address extraction
        addresses = []
        for line in results:
            # Look for lines with street patterns
            if any(word in line.lower() for word in ["ave", "avenue", "st", "street", "rd", "road", "dr", "drive", "ln", "lane"]):
                # Clean up the address
                clean_addr = line.split('Today')[-1].strip()
                if clean_addr:
                    addresses.append(clean_addr)
        
        return addresses or ["No addresses detected"]
    except Exception as e:
        logger.error(f"OCR processing error: {str(e)}")
        return ["Error processing image"]

# Route Optimization (unchanged from original)
def optimize_route(addresses: List[str]) -> List[str]:
    if len(addresses) < 2:
        return addresses

    try:
        logger.info(f"Starting optimization for {len(addresses)} addresses")
        locations = []
        
        for i, addr in enumerate(addresses):
            try:
                logger.info(f"Geocoding address {i+1}: {addr}")
                geocode_response = requests.get(
                    f"https://api.openrouteservice.org/geocode/search",
                    params={"api_key": config["ORS_API_KEY"], "text": addr, "size": 1},
                    timeout=10
                )
                geocode_response.raise_for_status()
                data = geocode_response.json()
                features = data.get("features", [])
                if not features:
                    logger.warning(f"No geocode results for: {addr}")
                    continue

                coords = features[0]["geometry"]["coordinates"]
                locations.append({
                    "id": f"loc_{i}",
                    "name": addr,
                    "lon": coords[0],
                    "lat": coords[1]
                })
                logger.info(f"Geocoded to: {coords[1]}, {coords[0]}")

            except Exception as geocode_error:
                logger.error(f"Geocoding failed for {addr}: {str(geocode_error)}")
                continue

        if len(locations) < 2:
            logger.warning("Not enough successfully geocoded addresses (need at least 2)")
            return addresses

        # Prepare optimization request
        jobs = [{
            "id": i + 1,
            "location": [loc["lon"], loc["lat"]],
            "description": loc["name"]
        } for i, loc in enumerate(locations)]

        vehicle_start = locations[0]
        vehicle_end = locations[-1]

        vehicles = [{
            "id": 1,
            "profile": "driving-car",
            "start": [vehicle_start["lon"], vehicle_start["lat"]],
            "end": [vehicle_end["lon"], vehicle_end["lat"]],
        }]

        payload = {
            "jobs": jobs,
            "vehicles": vehicles
        }

        logger.info(f"Sending ORS optimization payload: {json.dumps(payload, indent=2)}")

        # Call ORS optimization endpoint
        response = requests.post(
            "https://api.openrouteservice.org/optimization",
            headers={"Authorization": config["ORS_API_KEY"], "Content-Type": "application/json"},
            json=payload,
            timeout=30
        )
        logger.info(f"ORS response status: {response.status_code}")
        response.raise_for_status()
        data = response.json()

        if "routes" not in data or not data["routes"]:
            logger.error("No routes in ORS response")
            raise Exception("ORS returned no solution")

        # Extract optimized job order
        optimized_route = []
        steps = data["routes"][0]["steps"]

        for step in steps:
            if step["type"] == "job":
                job_id = step["id"]
                addr = next(loc["name"] for loc in locations if loc["id"] == f"loc_{job_id - 1}")
                optimized_route.append(addr)

        logger.info(f"Optimized route: {optimized_route}")
        return optimized_route

    except Exception as e:
        logger.error(f"Optimization failed: {str(e)}", exc_info=True)
        return addresses

# Main App (unchanged from original)
def main():
    if 'authenticated' not in st.session_state:
        st.session_state.authenticated = False
    if 'addresses' not in st.session_state:
        st.session_state.addresses = []
    if 'optimized_route' not in st.session_state:
        st.session_state.optimized_route = []
    if 'gate_codes' not in st.session_state:
        st.session_state.gate_codes = []
    if 'depot' not in st.session_state:
        st.session_state.depot = "7300 N Silverbell Rd, Tucson, AZ"
    if 'route_details' not in st.session_state:
        st.session_state.route_details = []

    # Login Page
    if not st.session_state.authenticated:
        st.title("ROUTEMIND")
        st.subheader("Login to Your Account")
        
        with st.form("login_form"):
            username = st.text_input("Username")
            password = st.text_input("Password", type="password")
            submit_button = st.form_submit_button("Login")
            
            if submit_button:
                if verify_user(username, password):
                    st.session_state.authenticated = True
                    st.rerun()
                else:
                    st.error("Invalid credentials")

    # Main Application
    else:
        st.title("ROUTEMIND")
        
        # Depot Selection
        st.header("Select Depot")
        st.session_state.depot = st.selectbox("Choose depot location", DEPOTS, index=0)
        
        # File Upload Section
        st.header("Upload Address Images")
        uploaded_files = st.file_uploader(
            "Choose images containing addresses", 
            type=["jpg", "jpeg", "png"], 
            accept_multiple_files=True
        )
        
        if uploaded_files:
            if st.button("Process Images"):
                all_addresses = []
                for uploaded_file in uploaded_files:
                    image_bytes = uploaded_file.read()
                    addresses = process_image(image_bytes)
                    if addresses!="LIST" and addresses[0] != "No addresses detected":
                        all_addresses.extend(addresses)
                
                if all_addresses:
                    st.session_state.addresses = all_addresses
                    st.success(f"Found {len(all_addresses)} addresses")
                else:
                    st.warning("No addresses found in the uploaded images")
        
        # Display Extracted Addresses
        if st.session_state.addresses:
            st.header("Extracted Addresses")
            for i, address in enumerate(st.session_state.addresses):
                st.write(f"{i+1}. {address}")
            
        if config.get("SUPABASE"):
            try:
                response = config["SUPABASE"].table("gate_codes").select("*").execute()
                st.session_state.gate_codes = response.data
            except Exception as e:
                st.error(f"Error fetching gate codes: {str(e)}")
            
            # Optimize Route
            if st.button("Optimize Route"):
                try:
                    optimized, route_details = optimize_route_with_metrics(
                        st.session_state.addresses, 
                        st.session_state.depot
                    )
                    st.session_state.optimized_route = optimized
                    st.session_state.route_details = route_details
                    st.success("Route optimized successfully!")
                    
                    # Display map
                    show_map_with_route(st.session_state.depot, st.session_state.route_details)
                    
                except Exception as e:
                    st.error(f"Optimization failed: {str(e)}")
        
        # Display Optimized Route with Metrics
        if st.session_state.optimized_route and st.session_state.route_details:
            st.header("Optimized Route Details")
            
            route_data = []
            total_distance = 0
            total_time = 0
            
            for i, detail in enumerate(st.session_state.route_details):
                gate_code = next(
                    (item["Gate Code"] for item in st.session_state.gate_codes 
                     if item.get("Address", "").lower() == detail['address'].lower()),
                    "No gate code found"
                )
                
                route_data.append({
                    "Stop": i+1,
                    "Address": detail['address'],
                    "Distance (km)": f"{detail['distance']:.2f}",
                    "Time (min)": f"{detail['time']:.2f}",
                    "Gate Code": gate_code
                })
                
                total_distance += detail['distance']
                total_time += detail['time']
            
            st.dataframe(route_data)
            
            col1, col2 = st.columns(2)
            with col1:
                st.metric("Total Distance", f"{total_distance:.2f} km")
            with col2:
                st.metric("Total Time", f"{total_time:.2f} minutes")
            
            if len(st.session_state.optimized_route) > 0:
                base_url = "https://www.google.com/maps/dir/?api=1"
                origin = f"origin={st.session_state.depot.replace(' ', '+')}"
                destination = f"destination={st.session_state.optimized_route[-1].replace(' ', '+')}"
                
                if len(st.session_state.optimized_route) > 1:
                    waypoints = "&waypoints=" + "|".join(
                        [addr.replace(' ', '+') for addr in st.session_state.optimized_route[:-1]]
                    )
                else:
                    waypoints = ""
                
                maps_url = f"{base_url}&{origin}&{destination}{waypoints}"
                st.markdown(f"[Open in Google Maps]({maps_url})")
        
        if st.button("Logout"):
            st.session_state.authenticated = False
            st.session_state.addresses = []
            st.session_state.optimized_route = []
            st.session_state.route_details = []
            st.rerun()

def show_map_with_route(depot, route_details):
    st.subheader("Route Visualization")
    st.write("### Route Overview")
    st.write(f"**Depot:** {depot}")
    
    for i, detail in enumerate(route_details):
        st.write(f"**Stop {i+1}:** {detail['address']}")
        st.write(f"- Distance from previous: {detail['distance']:.2f} km")
        st.write(f"- Estimated time: {detail['time']:.2f} minutes")
        st.write("---")

def optimize_route_with_metrics(addresses, depot):
    """Mock implementation of route optimization with metrics"""
    optimized_order = sorted(addresses)
    route_details = []
    previous_point = depot
    
    for address in optimized_order:
        distance = 5 + (hash(address) % 16)
        time = 10 + (hash(address) % 21)
        
        route_details.append({
            'address': address,
            'distance': distance,
            'time': time
        })
        
        previous_point = address
    
    return optimized_order, route_details

if __name__ == "__main__":
    main()
