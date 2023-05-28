import datetime
import branca.colormap as cm
import ee
import streamlit as st
import folium
from streamlit_folium import folium_static
import geopandas as gpd
import os
from dotenv import load_dotenv
load_dotenv()

# Initialize the Earth Engine library
sa = os.getenv('SA')
key = os.getenv('KEY')
ee.Initialize(key)

st.set_page_config(
    page_title="GEE Webinar",
    page_icon="🧊",
    layout="wide",
    initial_sidebar_state="expanded",
    menu_items={
        'About': "# Gee Webinar. This is an *GDG Nairobi* cool Gee app!"
    }
)

# Streamlit app
st.title("Water Quality Analysis using Google Earth Engine and Sentinel-2 Imagery")

coordinate_input = st.sidebar.text_input("Enter a coordinate (comma-separated latitude and longitude):", "1.845125, 35.304635")
start_date = st.sidebar.date_input("Start date:", value=datetime.date(2020, 1, 1))
end_date = st.sidebar.date_input("End date:", value=datetime.date(2020, 12, 31))
buffer_size = float(st.sidebar.text_input("Buffer size (km):", "2"))


# Define a method for displaying Earth Engine image tiles on a folium map.
def add_ee_layer(self, ee_object, vis_params, name):
    try:
        # display ee.Image()
        if isinstance(ee_object, ee.image.Image):
            map_id_dict = ee.Image(ee_object).getMapId(vis_params)
            folium.raster_layers.TileLayer(
                tiles=map_id_dict['tile_fetcher'].url_format,
                attr='Google Earth Engine',
                name=name,
                overlay=True,
                control=True
            ).add_to(self)
        # display ee.ImageCollection()
        elif isinstance(ee_object, ee.imagecollection.ImageCollection):
            ee_object_new = ee_object.mosaic()
            map_id_dict = ee.Image(ee_object_new).getMapId(vis_params)
            folium.raster_layers.TileLayer(
                tiles=map_id_dict['tile_fetcher'].url_format,
                attr='Google Earth Engine',
                name=name,
                overlay=True,
                control=True
            ).add_to(self)
        # display ee.Geometry()
        elif isinstance(ee_object, ee.geometry.Geometry):
            folium.GeoJson(
                data=ee_object.getInfo(),
                name=name,
                overlay=True,
                control=True
            ).add_to(self)
        # display ee.FeatureCollection()
        elif isinstance(ee_object, ee.featurecollection.FeatureCollection):
            ee_object_new = ee.Image().paint(ee_object, 0, 2)
            map_id_dict = ee.Image(ee_object_new).getMapId(vis_params)
            folium.raster_layers.TileLayer(
                tiles=map_id_dict['tile_fetcher'].url_format,
                attr='Google Earth Engine',
                name=name,
                overlay=True,
                control=True
            ).add_to(self)

    except:
        print("Could not display {}".format(name))


# Add EE drawing method to folium.
folium.Map.add_ee_layer = add_ee_layer

# Calculate AOI
try:
    lat, lon = [float(coord) for coord in coordinate_input.split(",")]
    buffer_m = buffer_size * 1000
    aoi = ee.Geometry.Point([lon, lat]).buffer(buffer_m).bounds()
except ValueError:
    st.error("Invalid coordinate input. Please enter comma-separated latitude and longitude.")
    aoi = None

if aoi is not None:
    def calculate_ndti(image):
        red_band = image.select("B4")
        green_band = image.select("B3")
        return red_band.subtract(green_band).divide(red_band.add(green_band))


    # Get Sentinel-2 image
    s2_collection = ee.ImageCollection("COPERNICUS/S2") \
        .filterBounds(aoi) \
        .filterDate(str(start_date), str(end_date)) \
        .sort("CLOUD_COVER") \
        .first()

    # Calculate NDWI
    ndwi = s2_collection.normalizedDifference(["B3", "B8"])

    # Extract water bodies
    water_bodies = ndwi.gt(0).selfMask()

    ndti = calculate_ndti(s2_collection)
    ndti_clipped = ndti.updateMask(water_bodies)

    # Calculate min and max values of the clipped NDTI
    ndti_stats = ndti_clipped.reduceRegion(
        reducer=ee.Reducer.minMax(),
        geometry=aoi,
        scale=10,
        bestEffort=True
    )


    def calculate_mean_ndti(image, aoi):
        mean_ndti = image.reduceRegion(
            reducer=ee.Reducer.mean(),
            geometry=aoi,
            scale=10,
            bestEffort=True
        )
        return mean_ndti.get("B4").getInfo()


    ndti_min = ndti_stats.get("B4_min").getInfo()
    ndti_max = ndti_stats.get("B4_max").getInfo()

    # Calculate mean NDTI value
    mean_ndti = calculate_mean_ndti(ndti_clipped, aoi)
    st.write(f"Mean NDTI value: {mean_ndti}")

    # Normalize the NDTI raster to [0, 1]
    ndti_normalized = ndti_clipped.subtract(ndti_min).divide(ndti_max - ndti_min)

    # Stretch the values between 0 and 255
    ndti_stretched = ndti_normalized.multiply(255)

    # Save water bodies as shapefile
    if st.button("Save water bodies as shapefile"):
        water_bodies_gpd = gpd.GeoDataFrame.from_features(water_bodies)
        water_bodies_gpd.to_file("water_bodies.shp")

    # Visualize results
    map = folium.Map(location=[lat, lon], zoom_start=14)

    ndti_palette = ['00A600', '63C600', 'E6E600', 'E9BD3A', 'ECB176', 'EFC2B3', 'F2F2F2']
    # Create color map for NDTI values
    # Create a new color palette for NDTI values
    new_ndti_palette = ['#0000FF', '#3399FF', '#66CC00', '#FFFF00', '#FF9900', '#FF0000']

    # Create color map for NDTI values
    ndti_colormap = cm.LinearColormap(colors=new_ndti_palette, index=[-1, -0.5, 0, 0.5, 1], vmin=-1, vmax=1)
    ndti_colormap.caption = 'Turbidity Values'

    # Convert folium map to geemap for adding Earth Engine layers
    map.add_ee_layer(s2_collection, {"bands": ["B4", "B3", "B2"], "max": 3000}, "Sentinel-2")
    map.add_ee_layer(water_bodies, {"palette": "blue"}, "Water Bodies")
    map.add_ee_layer(ndti_stretched, {"min": 0, "max": 255, "palette": new_ndti_palette}, "NDTI Clipped")
    map.add_child(ndti_colormap)
    folium.LayerControl().add_to(map)

    folium_static(map, width=1000, height=600)

