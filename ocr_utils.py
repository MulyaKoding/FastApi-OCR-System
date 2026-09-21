import os
import io
import base64
import json
import re
from dotenv import load_dotenv
from groq import Groq
from PIL import Image

load_dotenv()

client = Groq(api_key=os.getenv("GROQ_API_KEY"))

# Model hanya diminta membaca teks + menemukan posisi KARTU (satu kotak besar),
# bukan posisi tiap baris teks. Model vision jauh lebih akurat untuk deteksi
# satu objek besar (kartu) dibanding menebak koordinat banyak teks kecil.
PROMPT = """Ekstrak data dari KTP (Kartu Tanda Penduduk) Indonesia ini.

Kembalikan HANYA JSON (tanpa markdown, tanpa penjelasan) dengan struktur PERSIS berikut:

{
  "nik": "16 digit angka",
  "nama": "nama lengkap",
  "tempat_lahir": "kota lahir",
  "tanggal_lahir": "DD-MM-YYYY",
  "jenis_kelamin": "Laki-laki atau Perempuan",
  "alamat": "alamat lengkap",
  "rt_rw": "RT/RW",
  "kel_desa": "kelurahan/desa",
  "kecamatan": "kecamatan",
  "agama": "agama",
  "status_perkawinan": "status perkawinan",
  "pekerjaan": "pekerjaan",
  "kewarganegaraan": "WNI atau WNA",
  "berlaku_hingga": "tanggal atau SEUMUR HIDUP"
}

Jika sebuah field tidak dapat dibaca sama sekali, isi dengan string kosong "".
Pastikan NIK hanya berisi 16 angka, tanpa spasi atau karakter lain."""


import cv2
import numpy as np

def detect_ktp_card_box(image_bytes: bytes) -> list:
    """
    Mendeteksi posisi fisik kartu KTP [x, y, w, h] dalam persen (0-100)
    menggunakan segmentasi warna HSV biru KTP & analisis kontur OpenCV.
    """
    try:
        nparr = np.frombuffer(image_bytes, np.uint8)
        img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
        if img is None:
            return [0, 0, 100, 100]

        h_img, w_img = img.shape[:2]
        img_area = w_img * h_img

        # 1) Segmentasi warna HSV untuk warna biru/sian khas KTP Indonesia
        hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
        lower_blue = np.array([75, 20, 30])
        upper_blue = np.array([135, 255, 255])
        mask = cv2.inRange(hsv, lower_blue, upper_blue)

        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (15, 15))
        closed = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)
        closed = cv2.dilate(closed, kernel, iterations=2)

        contours, _ = cv2.findContours(closed, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

        best_box = None
        max_area = 0

        for cnt in contours:
            area = cv2.contourArea(cnt)
            if area < 0.10 * img_area:
                continue

            x, y, w, h = cv2.boundingRect(cnt)
            aspect_ratio = w / float(h)

            # Rasio KTP standar ~1.58 (rentang 1.1 s/d 2.3)
            if 1.1 <= aspect_ratio <= 2.3:
                if area > max_area:
                    max_area = area
                    best_box = [
                        round((x / w_img) * 100, 2),
                        round((y / h_img) * 100, 2),
                        round((w / w_img) * 100, 2),
                        round((h / h_img) * 100, 2)
                    ]

        if best_box and max_area < 0.90 * img_area:
            return best_box

        # 2) Fallback kontur edge/Canny jika deteksi warna tidak maksimal
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        blurred = cv2.GaussianBlur(gray, (5, 5), 0)
        edged = cv2.Canny(blurred, 30, 150)
        kernel_sm = cv2.getStructuringElement(cv2.MORPH_RECT, (5, 5))
        dilated = cv2.dilate(edged, kernel_sm, iterations=2)

        contours, _ = cv2.findContours(dilated, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        for cnt in contours:
            area = cv2.contourArea(cnt)
            if area < 0.15 * img_area:
                continue
            x, y, w, h = cv2.boundingRect(cnt)
            aspect_ratio = w / float(h)
            if 1.1 <= aspect_ratio <= 2.3 and area > max_area:
                max_area = area
                best_box = [
                    round((x / w_img) * 100, 2),
                    round((y / h_img) * 100, 2),
                    round((w / w_img) * 100, 2),
                    round((h / h_img) * 100, 2)
                ]

        if best_box and max_area < 0.90 * img_area:
            return best_box

        return [0, 0, 100, 100]
    except Exception:
        return [0, 0, 100, 100]


def extract_ktp_with_groq(image_bytes: bytes, mime_type: str = "image/jpeg") -> dict:
    base64_image = base64.b64encode(image_bytes).decode("utf-8")

    try:
        response = client.chat.completions.create(
            model="qwen/qwen3.8-27b",
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:{mime_type};base64,{base64_image}"}
                        },
                        {"type": "text", "text": PROMPT}
                    ]
                }
            ],
            max_tokens=1024,
            response_format={"type": "json_object"}
        )
    except Exception as e:
        raise ValueError(f"Groq API error: {str(e)}")

    text = response.choices[0].message.content or ""
    cleaned = re.sub(r"```json\n?|```\n?", "", text).strip()

    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError:
        raise ValueError("Gagal memproses data KTP. Pastikan gambar jelas dan tidak blur.")

    nik_val = data.get("nik") if isinstance(data.get("nik"), str) else None
    nama_val = data.get("nama") if isinstance(data.get("nama"), str) else None

    if not nik_val and not nama_val:
        raise ValueError("Tidak dapat mendeteksi data KTP. Pastikan gambar adalah KTP yang valid.")

    # Gunakan OpenCV untuk menentukan batas fisik kartu KTP secara akurat
    data["card_box"] = detect_ktp_card_box(image_bytes)

    return data