try:
    import requests
    REQUESTS_AVAILABLE = True
except ImportError:
    REQUESTS_AVAILABLE = False
    
import json
from datetime import datetime

def get_weather_data(api_key=None, location=None):
    """
    Fetch weather data from OpenWeatherMap API.
    If no API key provided, returns mock data for testing.
    """
    if not api_key or not REQUESTS_AVAILABLE:
        # Mock data for testing
        return {
            'temp': '24',
            'condition': 'Partly Cloudy',
            'location': 'Your Location',
            'feels_like': '22',
            'humidity': '65',
            'wind': '12 km/h',
            'aqi': '42',
            'aqi_level': 'Good',
            'icon': '⛅'
        }
    
    try:
        # Use OpenWeatherMap API
        base_url = "http://api.openweathermap.org/data/2.5/weather"
        params = {
            'q': location or 'auto:ip',
            'appid': api_key,
            'units': 'metric'
        }
        
        response = requests.get(base_url, params=params, timeout=5)
        response.raise_for_status()
        data = response.json()
        
        # Map weather condition to emoji
        weather_id = data['weather'][0]['id']
        icon = _get_weather_icon(weather_id)
        
        # Get AQI data (requires separate API call)
        aqi_data = _get_aqi_data(api_key, data['coord']['lat'], data['coord']['lon'])
        
        return {
            'temp': str(int(data['main']['temp'])),
            'condition': data['weather'][0]['main'],
            'location': data['name'],
            'feels_like': str(int(data['main']['feels_like'])),
            'humidity': str(data['main']['humidity']),
            'wind': f"{int(data['wind']['speed'] * 3.6)} km/h",
            'aqi': str(aqi_data['aqi']),
            'aqi_level': aqi_data['level'],
            'icon': icon
        }
    except Exception as e:
        print(f"Weather fetch error: {e}")
        return None

def _get_weather_icon(weather_id):
    """Map OpenWeatherMap condition ID to emoji."""
    if weather_id < 300:
        return '⛈️'  # Thunderstorm
    elif weather_id < 400:
        return '🌧️'  # Drizzle
    elif weather_id < 600:
        return '🌧️'  # Rain
    elif weather_id < 700:
        return '❄️'  # Snow
    elif weather_id < 800:
        return '🌫️'  # Atmosphere (fog, mist, etc.)
    elif weather_id == 800:
        return '☀️'  # Clear
    elif weather_id == 801:
        return '🌤️'  # Few clouds
    elif weather_id == 802:
        return '⛅'  # Scattered clouds
    else:
        return '☁️'  # Cloudy

def _get_aqi_data(api_key, lat, lon):
    """Fetch Air Quality Index data."""
    try:
        url = "http://api.openweathermap.org/data/2.5/air_pollution"
        params = {
            'lat': lat,
            'lon': lon,
            'appid': api_key
        }
        
        response = requests.get(url, params=params, timeout=5)
        response.raise_for_status()
        data = response.json()
        
        aqi = data['list'][0]['main']['aqi']
        levels = ['Good', 'Fair', 'Moderate', 'Poor', 'Very Poor']
        
        return {
            'aqi': aqi * 50,  # Convert 1-5 scale to 0-250
            'level': levels[aqi - 1] if 1 <= aqi <= 5 else 'Unknown'
        }
    except:
        return {'aqi': 0, 'level': 'Unknown'}

if __name__ == '__main__':
    # Test the weather fetching
    weather = get_weather_data()
    print(json.dumps(weather, indent=2))
