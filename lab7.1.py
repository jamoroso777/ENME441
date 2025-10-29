import RPi.GPIO as GPIO
import socket

GPIO.setmode(GPIO.BCM)
led_pins = [17, 27, 22]
for pin in led_pins:
    GPIO.setup(pin, GPIO.OUT)

led_pwm = [GPIO.PWM(pin, 100) for pin in led_pins]
for pwm in led_pwm:
    pwm.start(0)

#helper function
def parsePOSTdata(data):
    data_dict = {}
    idx = data.find('\r\n\r\n') + 4
    if idx < 4:
        return data_dict
    data = data[idx:]
    data_pairs = data.split('&')
    for pair in data_pairs:
        key_val = pair.split('=')
        if len(key_val) == 2:
            data_dict[key_val[0]] = key_val[1]
    return data_dict

#HTML
def html_page(selected_led=0, brightness=0):
    led_states = ["", "", ""]
    led_states[selected_led] = "checked"

    return f"""<!DOCTYPE html>
<html>
<head>
<title>LED Brightness Control</title>
<style>
  body {{
    font-family: Arial, sans-serif;
  }}
  .control-box {{
    border: 1px solid #ccc;
    width: 240px;
    padding: 10px;
    border-radius: 8px;
  }}
  input[type=range] {{
    width: 100%;
  }}
</style>
</head>
<body>
<h2>LED Brightness Control</h2>
<div class="control-box">
  <form method="POST" action="/">
    <b>Select LED:</b><br>
    <input type="radio" name="led" value="0" {led_states[0]}> LED 1<br>
    <input type="radio" name="led" value="1" {led_states[1]}> LED 2<br>
    <input type="radio" name="led" value="2" {led_states[2]}> LED 3<br><br>

    <label for="brightness"><b>Brightness:</b></label><br>
    <input type="range" id="brightness" name="brightness" min="0" max="100" value="{brightness}"><br><br>

    <input type="submit" value="Change Brightness">
  </form>
  <p>Current LED: {selected_led + 1}, Brightness: {brightness}%</p>
</div>
</body>
</html>"""

#Server
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

        selected_led = 0
        brightness = 0

        if "POST" in request:
            data = parsePOSTdata(request)
            if "led" in data and "brightness" in data:
                selected_led = int(data["led"])
                brightness = int(data["brightness"])
                brightness_levels[selected_led] = brightness
                led_pwm[selected_led].ChangeDutyCycle(brightness)
                print(f"LED {selected_led + 1} set to {brightness}%")

        response_body = html_page(selected_led, brightness_levels[selected_led])
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

#main
if __name__ == "__main__":
    try:
        run_server()
    except KeyboardInterrupt:
        print("\nServer stopped.")
    finally:
        for pwm in led_pwm:
            pwm.stop()
        GPIO.cleanup()
