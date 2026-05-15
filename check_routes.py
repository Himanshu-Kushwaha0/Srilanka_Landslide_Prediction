from APP.landslide_app.app import app

print("Registered Flask Routes:")
for rule in app.url_map.iter_rules():
    print(f"  {rule}")
