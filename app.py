import os, uuid, io
from datetime import datetime
from flask import Flask, jsonify, request, render_template, abort
from supabase import create_client, Client
from dotenv import load_dotenv
try:
    from PIL import Image
    import pillow_heif
    pillow_heif.register_heif_opener()  # enables HEIC/HEIF support
    PILLOW = True
except ImportError:
    PILLOW = False

load_dotenv()

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 20 * 1024 * 1024  # 20 MB

SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_KEY = os.environ["SUPABASE_KEY"]
STADIA_KEY   = os.environ.get("STADIA_API_KEY", "")
BUCKET       = "audit-photos"

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

def today_str():
    months = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec']
    d = datetime.now()
    return f"{d.day} {months[d.month-1]} {d.year}"


def convert_to_jpeg(file_bytes, content_type):
    """Convert any image (including HEIC) to JPEG for browser compatibility."""
    if not PILLOW:
        return file_bytes, content_type, 'jpg'
    try:
        img = Image.open(io.BytesIO(file_bytes))
        if img.mode in ('RGBA', 'P', 'LA'):
            bg = Image.new('RGB', img.size, (255, 255, 255))
            if img.mode == 'P':
                img = img.convert('RGBA')
            bg.paste(img, mask=img.split()[-1] if img.mode in ('RGBA','LA') else None)
            img = bg
        elif img.mode != 'RGB':
            img = img.convert('RGB')
        out = io.BytesIO()
        img.save(out, format='JPEG', quality=85)
        return out.getvalue(), 'image/jpeg', 'jpg'
    except Exception:
        return file_bytes, content_type, 'jpg'

# ── Pages ────────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return render_template("index.html", stadia_key=STADIA_KEY)

@app.route("/api/config")
def config():
    return jsonify({"stadia_key": STADIA_KEY})

# ── Roads ────────────────────────────────────────────────────────────────────

@app.route("/api/roads", methods=["GET"])
def get_roads():
    roads      = supabase.table("roads").select("*").order("created_at").execute().data
    photos     = supabase.table("photos").select("*").order("created_at").execute().data
    complaints = supabase.table("complaints").select("*").order("created_at").execute().data
    links      = supabase.table("drive_links").select("*").order("created_at").execute().data

    result = []
    for r in roads:
        rid = r["id"]
        result.append({
            "id": rid,
            "name": r["name"],
            "status": r["status"],
            "block": r.get("block", ""),
            "length": r.get("length", ""),
            "auditedOn": r.get("audited_on", ""),
            "width": r.get("width", ""),
            "condition": r.get("condition", ""),
            "coords": r.get("coords", []),
            "photos": [
                {"id": p["id"], "type": p.get("type","emoji"),
                 "e": p.get("emoji","📷"), "cap": p.get("caption",""),
                 "tag": p.get("tag",""), "src": p.get("public_url"),
                 "storagePath": p.get("storage_path"), "driveUrl": p.get("drive_url","")}
                for p in photos if p["road_id"] == rid
            ],
            "complaints": [
                {"id": c["id"], "title": c["title"], "status": c["status"],
                 "date": c.get("date",""), "dept": c.get("dept",""), "link": c.get("link","")}
                for c in complaints if c["road_id"] == rid
            ],
            "driveLinks": [
                {"id": l["id"], "name": l["name"], "url": l["url"], "type": l.get("type","file")}
                for l in links if l["road_id"] == rid
            ]
        })
    return jsonify(result)

@app.route("/api/roads", methods=["POST"])
def create_road():
    data = request.json
    row = {
        "id": data.get("id") or "r_" + str(uuid.uuid4())[:8],
        "name": data["name"],
        "status": data.get("status", "pending"),
        "block": data.get("block", ""),
        "length": data.get("length", ""),
        "audited_on": data.get("auditedOn", ""),
        "width": data.get("width", ""),
        "condition": data.get("condition", ""),
        "coords": data.get("coords", [])
    }
    result = supabase.table("roads").insert(row).execute()
    return jsonify(result.data[0] if result.data else row), 201

@app.route("/api/roads/<road_id>", methods=["PATCH"])
def update_road(road_id):
    data = request.json
    field_map = {
        "name":"name","status":"status","block":"block","length":"length",
        "auditedOn":"audited_on","width":"width","condition":"condition","coords":"coords"
    }
    updates = {field_map[k]: v for k, v in data.items() if k in field_map}
    result = supabase.table("roads").update(updates).eq("id", road_id).execute()
    return jsonify(result.data[0] if result.data else {})

@app.route("/api/roads/<road_id>", methods=["DELETE"])
def delete_road(road_id):
    photos = supabase.table("photos").select("storage_path").eq("road_id", road_id).execute().data
    for p in photos:
        if p.get("storage_path"):
            try:
                supabase.storage.from_(BUCKET).remove([p["storage_path"]])
            except Exception:
                pass
    supabase.table("roads").delete().eq("id", road_id).execute()
    return jsonify({"ok": True})

# ── Photos ───────────────────────────────────────────────────────────────────

@app.route("/api/photos", methods=["POST"])
def create_photo():
    if request.content_type and "multipart" in request.content_type:
        file    = request.files.get("file")
        road_id = request.form.get("road_id")
        caption = request.form.get("caption", "Field photo")
        tag     = request.form.get("tag", "Field Photo")
        if not file or not road_id:
            abort(400, "Missing file or road_id")

        file_bytes = file.read()
        # Convert HEIC/HEIF and any non-web format to JPEG
        file_bytes, content_type, ext = convert_to_jpeg(file_bytes, file.content_type or "image/jpeg")
        path = f"{road_id}/{uuid.uuid4()}.{ext}"
        supabase.storage.from_(BUCKET).upload(
            path, file_bytes,
            file_options={"content-type": content_type}
        )
        public_url = f"{SUPABASE_URL}/storage/v1/object/public/{BUCKET}/{path}"
        row = {
            "id": "ph_" + str(uuid.uuid4())[:12],
            "road_id": road_id, "type": "image", "emoji": "📷",
            "caption": caption, "tag": tag,
            "storage_path": path, "public_url": public_url, "drive_url": ""
        }
    else:
        data = request.json
        row = {
            "id": "ph_" + str(uuid.uuid4())[:12],
            "road_id": data["road_id"], "type": "emoji",
            "emoji": data.get("emoji", "🖼"), "caption": data.get("caption", ""),
            "tag": data.get("tag", "Drive Link"),
            "storage_path": None, "public_url": None,
            "drive_url": data.get("driveUrl", "")
        }

    result = supabase.table("photos").insert(row).execute()
    inserted = result.data[0] if result.data else row
    return jsonify({
        "id": inserted["id"], "type": inserted["type"],
        "e": inserted.get("emoji","📷"), "cap": inserted.get("caption",""),
        "tag": inserted.get("tag",""), "src": inserted.get("public_url"),
        "storagePath": inserted.get("storage_path"), "driveUrl": inserted.get("drive_url","")
    }), 201

@app.route("/api/photos/<photo_id>", methods=["DELETE"])
def delete_photo(photo_id):
    photos = supabase.table("photos").select("storage_path").eq("id", photo_id).execute().data
    if photos and photos[0].get("storage_path"):
        try:
            supabase.storage.from_(BUCKET).remove([photos[0]["storage_path"]])
        except Exception:
            pass
    supabase.table("photos").delete().eq("id", photo_id).execute()
    return jsonify({"ok": True})

# ── Complaints ───────────────────────────────────────────────────────────────

@app.route("/api/complaints", methods=["POST"])
def create_complaint():
    data = request.json
    row = {
        "id": "BMP-" + datetime.now().strftime("%Y") + "-" + str(uuid.uuid4())[:4].upper(),
        "road_id": data["road_id"],
        "title": data["title"],
        "status": data.get("status", "open"),
        "date": data.get("date") or today_str(),
        "dept": data.get("dept", "BBMP Roads"),
        "link": data.get("link", "")
    }
    result = supabase.table("complaints").insert(row).execute()
    inserted = result.data[0] if result.data else row
    return jsonify({
        "id": inserted["id"], "title": inserted["title"],
        "status": inserted["status"], "date": inserted["date"],
        "dept": inserted["dept"], "link": inserted.get("link","")
    }), 201

@app.route("/api/complaints/<complaint_id>", methods=["PATCH"])
def update_complaint(complaint_id):
    data = request.json
    updates = {k: v for k, v in data.items() if k in ("status","title","dept","link")}
    result = supabase.table("complaints").update(updates).eq("id", complaint_id).execute()
    return jsonify(result.data[0] if result.data else {})

@app.route("/api/complaints/<complaint_id>", methods=["DELETE"])
def delete_complaint(complaint_id):
    supabase.table("complaints").delete().eq("id", complaint_id).execute()
    return jsonify({"ok": True})

# ── Drive Links ──────────────────────────────────────────────────────────────

@app.route("/api/links", methods=["POST"])
def create_link():
    data = request.json
    row = {
        "id": "dl_" + str(uuid.uuid4())[:8],
        "road_id": data["road_id"],
        "name": data["name"],
        "url": data["url"],
        "type": data.get("type", "file")
    }
    result = supabase.table("drive_links").insert(row).execute()
    inserted = result.data[0] if result.data else row
    return jsonify({"id": inserted["id"], "name": inserted["name"],
                    "url": inserted["url"], "type": inserted["type"]}), 201

@app.route("/api/links/<link_id>", methods=["DELETE"])
def delete_link(link_id):
    supabase.table("drive_links").delete().eq("id", link_id).execute()
    return jsonify({"ok": True})

# ── Seed (first-run) ─────────────────────────────────────────────────────────

@app.route("/api/seed", methods=["POST"])
def seed():
    """Called by the frontend on first load — seeds default roads once only."""
    # Check a dedicated flag so we never re-seed even if all roads are deleted
    try:
        flag = supabase.table("seed_flag").select("id").limit(1).execute().data
        if flag:
            return jsonify({"seeded": False, "msg": "Already seeded"})
    except Exception:
        pass  # table may not exist yet — proceed to seed

    defaults = [
        {"id":"r60ft","name":"60 Feet Road","status":"audited","block":"3rd – 7th Block","length":"2.1 km","audited_on":"15 Nov 2024","width":"1.2 – 1.8 m","condition":"Fair","coords":[[12.9279,77.6103],[12.9278,77.6145],[12.9278,77.6190],[12.9279,77.6230],[12.9280,77.6275],[12.9282,77.6315],[12.9285,77.6355],[12.9288,77.6400],[12.9290,77.6435]]},
        {"id":"r80ft","name":"80 Feet Road","status":"audited","block":"1st – 7th Block","length":"1.8 km","audited_on":"20 Nov 2024","width":"1.5 – 2.0 m","condition":"Good","coords":[[12.9450,77.6245],[12.9420,77.6243],[12.9390,77.6242],[12.9360,77.6240],[12.9330,77.6238],[12.9300,77.6237],[12.9270,77.6236],[12.9240,77.6235],[12.9210,77.6234]]},
        {"id":"rsarj","name":"Sarjapur Road","status":"partial","block":"7th Block Boundary","length":"~1.2 km audited","audited_on":"10 Dec 2024","width":"0.8 – 1.2 m","condition":"Poor","coords":[[12.9150,77.6450],[12.9190,77.6400],[12.9230,77.6360],[12.9270,77.6320],[12.9310,77.6285],[12.9340,77.6265],[12.9370,77.6255]]},
        {"id":"r100ft","name":"Outer Ring Road (100 Ft)","status":"partial","block":"5th – 7th Block North","length":"1.4 km (0.8 km done)","audited_on":"01 Dec 2024","width":"1.0 – 1.5 m","condition":"Poor","coords":[[12.9420,77.6095],[12.9420,77.6140],[12.9418,77.6185],[12.9415,77.6230],[12.9412,77.6275],[12.9410,77.6320],[12.9408,77.6365]]},
        {"id":"rjnc","name":"Jyoti Nivas College Road","status":"audited","block":"5th – 7th Block","length":"0.5 km","audited_on":"12 Dec 2024","width":"1.0 – 1.5 m","condition":"Good","coords":[[12.9350,77.6305],[12.9362,77.6295],[12.9375,77.6288],[12.9390,77.6280],[12.9405,77.6270]]},
        {"id":"r3main","name":"3rd Main Road, 3rd Block","status":"audited","block":"3rd Block","length":"0.6 km","audited_on":"28 Nov 2024","width":"0.8 – 1.2 m","condition":"Fair","coords":[[12.9350,77.6125],[12.9365,77.6127],[12.9380,77.6129],[12.9395,77.6131],[12.9410,77.6133]]},
        {"id":"r7cross","name":"7th Cross Road","status":"audited","block":"4th – 5th Block","length":"0.9 km","audited_on":"05 Dec 2024","width":"0.9 – 1.3 m","condition":"Fair","coords":[[12.9310,77.6160],[12.9312,77.6195],[12.9313,77.6225],[12.9314,77.6255]]},
        {"id":"r12main","name":"12th Main Road","status":"partial","block":"5th Block","length":"0.8 km (0.4 km done)","audited_on":"10 Dec 2024","width":"0.7 – 1.0 m","condition":"Poor","coords":[[12.9280,77.6255],[12.9295,77.6257],[12.9310,77.6259],[12.9325,77.6261],[12.9340,77.6262]]},
        {"id":"r5main","name":"5th Main Road","status":"pending","block":"4th Block","length":"0.7 km","audited_on":None,"width":None,"condition":None,"coords":[[12.9340,77.6170],[12.9355,77.6172],[12.9370,77.6174],[12.9385,77.6176]]},
        {"id":"r8cross","name":"8th Cross Road","status":"pending","block":"3rd – 4th Block","length":"0.8 km","audited_on":None,"width":None,"condition":None,"coords":[[12.9295,77.6130],[12.9297,77.6168],[12.9298,77.6200],[12.9299,77.6232]]},
        {"id":"r11cross","name":"11th Cross Road","status":"pending","block":"6th – 7th Block","length":"0.9 km","audited_on":None,"width":None,"condition":None,"coords":[[12.9245,77.6175],[12.9247,77.6215],[12.9248,77.6255],[12.9249,77.6295]]},
    ]
    supabase.table("roads").insert(defaults).execute()
    # Write the flag so this never runs again
    try:
        supabase.table("seed_flag").insert({"id": "done"}).execute()
    except Exception:
        pass
    return jsonify({"seeded": True, "count": len(defaults)})

# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
