import os
print("Files in current directory:")
for f in os.listdir('.'):
    if f.endswith('.js') or f.endswith('.py'):
        print(f"  {f} ({os.path.getsize(f)} bytes)")
