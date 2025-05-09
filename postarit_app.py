import geopandas as gpd
from shapely.geometry import Point, Polygon
from shapely.ops import unary_union
from lxml import etree
import streamlit as st
import io

def read_kml_polygon(file):
    from shapely.geometry import Polygon
    from lxml import etree

    doc = etree.parse(file)
    ns = {'kml': 'http://www.opengis.net/kml/2.2'}
    coords = doc.xpath('//kml:Polygon//kml:coordinates', namespaces=ns)

    if not coords:
        raise ValueError("No Polygon coordinates found in KML.")

    all_polygons = []
    for coord in coords:
        coord_text = coord.text.strip()
        points = []
        for pair in coord_text.split():
            lon, lat, *_ = map(float, pair.split(','))
            points.append((lon, lat))
        if len(points) >= 3:
            all_polygons.append(Polygon(points))

    if not all_polygons:
        raise ValueError("No valid Polygon geometries constructed.")

    return gpd.GeoSeries(all_polygons, crs="EPSG:4326")

def project_gdf(gdf):
    return gdf.to_crs(epsg=3879)  # ETRS-TM35FIN (accurate for Finland)

st.title("Postal Code Delivery Zone Checker")

geojson_file = st.file_uploader("Upload Finland postal code GeoJSON", type=["geojson"])
kml_file = st.file_uploader("Upload Delivery Area KML", type=["kml"])
coords = st.text_input("Enter store coordinates (lat, lon)", value="60.450443736980425, 22.263339299434875")
radius_meters = st.number_input("Enter max delivery distance in meters", value=7500)

if geojson_file and kml_file and coords:
    try:
        lat, lon = map(float, coords.split(","))
        point = Point(lon, lat)

        st.info("Loading data...")
        postal_codes = gpd.read_file(geojson_file)
        delivery_area = read_kml_polygon(kml_file)

        postal_codes = project_gdf(postal_codes)
        delivery_area = delivery_area.to_crs(epsg=3879)
        point_proj = gpd.GeoSeries([point], crs="EPSG:4326").to_crs(epsg=3879).iloc[0]

        circle = point_proj.buffer(radius_meters)

        postal_codes['intersects_buffer'] = postal_codes.geometry.intersects(circle)
        filtered = postal_codes[postal_codes['intersects_buffer']].copy()

        delivery_union = unary_union(delivery_area.geometry)
        filtered['intersects_delivery'] = filtered.geometry.intersects(delivery_union)
        filtered = filtered[filtered['intersects_delivery']].copy()

        final = []
        for _, row in filtered.iterrows():
            total_area = row.geometry.area
            delivery_intersection = row.geometry.intersection(delivery_union)
            radius_intersection = row.geometry.intersection(circle)
            combined_intersection = delivery_intersection.intersection(circle)

            if not combined_intersection.is_empty:
                delivery_pct = delivery_intersection.area / total_area
                radius_pct = radius_intersection.area / total_area
                total_pct = combined_intersection.area / total_area

                if total_pct >= 0.02:
                    final.append((
                        row.get("postinumeroalue", "Unknown"),
                        round(delivery_pct, 2),
                        round(radius_pct, 2),
                        round(total_pct, 2)
                    ))

        if final:
            st.success("Postal codes with >=2% total (delivery ∩ radius) overlap:")
            for code, delivery_pct, radius_pct, total_pct in final:
                st.write(f"{code}: Delivery area {delivery_pct*100:.0f}%, delivery radius {radius_pct*100:.0f}%, total {total_pct*100:.0f}%")
        else:
            st.warning("No postal code areas met the overlap criteria.")
    except Exception as e:
        st.error(f"Something went wrong: {e}")