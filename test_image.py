import os

path = "image.jpg"
full_path = os.path.abspath(path)

print(f"Looking for: {full_path}")
print(f"Exists: {os.path.exists(path)}")

if os.path.exists(path):
    print(f"✅ File size: {os.path.getsize(path)} bytes")
else:
    print("❌ File not found")
    print("\nImage files in current folder:")
    for f in os.listdir('.'):
        if f.lower().endswith(('.jpg', '.jpeg', '.png')):
            print(f"  - {f}")
