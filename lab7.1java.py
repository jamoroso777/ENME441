import RPi.GPIO as GPIO
import socket

GPIO.setmode(GPIO.BCM)
led_pins = [17, 27, 22]
for pin in led_pins:
    GPIO.setup(pin, GPIO.OUT)
led_pwm = [GPIO.PWM(pin, 1000) for pin in led_pins]
for pwm in led_pwm:
    pwm.start(0)

#helper function
def parsePOSTdata(data):
    data_dict = {}
    idx = data.find('\r\n\r\n') + 4 
    if idx < 4:
        return data_dict
    data = data[idx:]
    pairs = data.split('&')
    for pair in pairs:
        key_val = pair.split('=')
        if len(key_val) == 2:
            data_dict[key_val[0]] = key_val[1]
    return data_dict

#HTML with java code help from LLM
def html_page(brightness_levels):
    return f"""<!DOCTYPE html>
<html>
<head>
<title>LED Brightness Control (Live)</title>
<style>
  body {{
    font-family: Arial, sans-serif;
  }}
  .control-box {{
    border: 1px solid #ccc;
    width: 280px;
    padding: 10px;
    border-radius: 8px;
  }}
  .led-label {{
    font-weight: bold;
  }}
  input[type=range] {{
    width: 100%;
  }}
</style>
<script>
function updateBrightness(led, value) {{
  document.getElementById("label" + led).innerText = value + "%";
  fetch("/", {{
    method: "POST",
    headers: {{
      "Content-Type": "application/x-www-form-urlencoded"
    }},
    body: "led=" + led + "&brightness=" + value
  }});
}}
</script>
</head>
<body>
<h2>LED Brightness Control (Live)</h2>
<div class="control-box">
  <div>
    <span class="led-label">LED 1:</span>
    <input type="range" min="0" max="100" value="{brightness_levels[0]}" oninput="updateBrightness(0, this.value)">
    <span id="label0">{brightness_levels[0]}%</span>
  </div><br>
  <div>
    <span class="led-label">LED 2:</span>
    <input type="range" min="0" max="100" value="{brightness_levels[1]}" oninput="updateBrightness(1, this.value)">
    <span id="label1">{brightness_levels[1]}%</span>
  </div><br>
  <div>
    <span class="led-label">LED 3:</span>
    <input type="range" min="0" max="100" value="{brightness_levels[2]}" oninput="updateBrightness(2, this.value)">
    <span id="label2">{brightness_levels[2]}%</span>
  </div>
</div>
</body>
</html>"""

#server
def run_server():
    brightness_levels = [0, 0, 0]
    host, port = '', 8080
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind((host, port))
    s.listen(1)
    print(f"Server running on port {port}...")

    while True:
        conn, addr = s.accept()
        request = conn.recv(1024).decode('utf-8')
        print(f"Request from {addr}")
        print(request)

        if "POST" in request:
            data = parsePOSTdata(request)
            if "led" in data and "brightness" in data:
                led = int(data["led"])
                brightness = int(data["brightness"])
                brightness_levels[led] = brightness
                led_pwm[led].ChangeDutyCycle(brightness)
                print(f"LED {led + 1} set to {brightness}%")

        response_body = html_page(brightness_levels)
        response = (
            "HTTP/1.1 200 OK\r\n"
            "Content-Type: text/html\r\n"
            f"Content-Length: {len(response_body)}\r\n"
            "Connection: close\r\n"
            "\r\n"
            + response_body
        )
        conn.sendall(response.encode('utf-8'))
        conn.close()

    if __name__ == "__main__":
    try:
        run_server()
        print("server started on port 8080")
   except KeyboardInterrupt:
        pass
    finally:
        for pwm in led_pwm:
            pwm.stop()
        GPIO.cleanup()