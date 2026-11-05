import streamlit as st

st.set_page_config(
    page_title="Arduino Universal Control Center",
    page_icon="🔌",
    layout="wide"
)

st.title("🔌 Arduino Universal Control Center")
st.caption("Browser-based USB serial control | Arduino Uno | 115200 baud")

st.info(
    "Connect your Arduino by USB, then click Connect and select its serial port. "
    "Use Chrome or Edge on the computer physically connected to the board."
)

HTML = """
<div id="arduino-panel">
  <div class="topbar">
    <span id="connection-status">● Disconnected</span>
    <button id="connect">Connect Arduino</button>
    <button id="disconnect" disabled>Disconnect</button>
  </div>

  <div class="section">
    <h3>Safety controls</h3>
    <button id="arm" disabled>ARM OUTPUTS</button>
    <button id="disarm" disabled>DISARM</button>
    <button id="estop" class="danger" disabled>EMERGENCY STOP</button>
    <button id="reset" disabled>Reset E-STOP</button>
    <p id="safety-status">Outputs are disarmed.</p>
  </div>

  <div class="section">
    <h3>Digital pin control</h3>
    <label>Pin
      <select id="digital-pin"></select>
    </label>
    <button id="set-output" disabled>Configure OUTPUT</button>
    <button id="set-input" disabled>Configure INPUT</button>
    <button id="digital-on" disabled>ON</button>
    <button id="digital-off" disabled>OFF</button>
  </div>

  <div class="section">
    <h3>PWM control</h3>
    <label>PWM pin
      <select id="pwm-pin"></select>
    </label>
    <label>Duty value: <b id="pwm-value">0</b> / 255</label>
    <input id="pwm-slider" type="range" min="0" max="255" value="0">
    <button id="send-pwm" disabled>Apply PWM</button>
  </div>

  <div class="section">
    <h3>Analog inputs</h3>
    <div class="analog-grid" id="analog-grid"></div>
    <canvas id="analog-chart" width="900" height="260"></canvas>
    <button id="download-csv">Download sensor CSV</button>
  </div>

  <div class="section">
    <h3>Serial monitor</h3>
    <pre id="terminal"></pre>
  </div>
</div>
"""

CSS = """
#arduino-panel {
  font-family: sans-serif;
  color: var(--st-text-color);
}
#arduino-panel .section {
  border: 1px solid var(--st-border-color);
  border-radius: 12px;
  padding: 16px;
  margin: 14px 0;
}
#arduino-panel .topbar {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}
#arduino-panel button {
  border: 1px solid var(--st-border-color);
  border-radius: 8px;
  padding: 9px 13px;
  margin: 4px;
  cursor: pointer;
  color: var(--st-text-color);
  background: var(--st-secondary-background-color);
}
#arduino-panel button:disabled {
  opacity: .4;
  cursor: not-allowed;
}
#arduino-panel button.danger {
  background: #a52323;
  color: white;
  border-color: #a52323;
}
#arduino-panel select {
  padding: 8px;
  margin: 6px;
  border-radius: 6px;
}
#arduino-panel input[type=range] {
  width: min(500px, 90%);
  display: block;
  margin: 12px 0;
}
#arduino-panel .analog-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(100px, 1fr));
  gap: 10px;
  margin: 12px 0;
}
#arduino-panel .analog-card {
  background: var(--st-secondary-background-color);
  padding: 12px;
  border-radius: 8px;
}
#arduino-panel .analog-card strong {
  display: block;
  font-size: 22px;
  margin-top: 5px;
}
#arduino-panel canvas {
  width: 100%;
  max-height: 260px;
  border: 1px solid var(--st-border-color);
  border-radius: 8px;
}
#arduino-panel #terminal {
  background: #101820;
  color: #9ee7a1;
  height: 180px;
  overflow: auto;
  padding: 12px;
  border-radius: 8px;
  white-space: pre-wrap;
}
"""

JS = r"""
export default function({ parentElement }) {
  const root = parentElement;
  const $ = (id) => root.querySelector("#" + id);

  let port = null;
  let reader = null;
  let writer = null;
  let readTask = null;
  let heartbeatTimer = null;
  let armed = false;
  let estop = false;
  let lineBuffer = "";
  let writeQueue = Promise.resolve();
  let history = [];

  const pins = Array.from({length: 12}, (_, i) => i + 2);
  const pwmPins = [3, 5, 6, 9, 10, 11];

  pins.forEach(p => $("digital-pin").add(new Option("D" + p, p)));
  pwmPins.forEach(p => $("pwm-pin").add(new Option("D" + p, p)));

  $("analog-grid").innerHTML = Array.from({length: 6}, (_, i) =>
    `<div class="analog-card">A${i}<strong id="a${i}">---</strong></div>`
  ).join("");

  function log(message) {
    const terminal = $("terminal");
    terminal.textContent += message + "\n";
    terminal.scrollTop = terminal.scrollHeight;
  }

  function setStatus(message) {
    $("connection-status").textContent = message;
  }

  function updateControls(connected) {
    $("connect").disabled = connected;
    $("disconnect").disabled = !connected;
    ["arm", "disarm", "estop", "reset",
     "set-output", "set-input", "digital-on",
     "digital-off", "send-pwm"].forEach(id => {
       $(id).disabled = !connected;
    });
  }

  async function send(command) {
    if (!writer) {
      log("NOT CONNECTED: " + command);
      return;
    }

    writeQueue = writeQueue.then(async () => {
      await writer.write(new TextEncoder().encode(command + "\n"));
      log("> " + command);
    });

    return writeQueue;
  }

  function drawChart() {
    const canvas = $("analog-chart");
    const ctx = canvas.getContext("2d");
    const w = canvas.width, h = canvas.height;
    ctx.clearRect(0, 0, w, h);

    ctx.strokeStyle = "#888";
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.moveTo(35, 10);
    ctx.lineTo(35, h - 25);
    ctx.lineTo(w - 10, h - 25);
    ctx.stroke();

    const series = history.slice(-100);
    if (series.length < 2) return;

    for (let channel = 0; channel < 6; channel++) {
      ctx.beginPath();
      series.forEach((row, index) => {
        const x = 35 + index * (w - 50) / 99;
        const y = h - 25 - row.values[channel] * (h - 45) / 1023;
        if (index === 0) ctx.moveTo(x, y);
        else ctx.lineTo(x, y);
      });
      // Distinct line styles without requiring a colour palette.
      ctx.setLineDash(channel % 2 ? [5, 3] : []);
      ctx.stroke();
    }
    ctx.setLineDash([]);
  }

  function handleLine(line) {
    if (!line) return;
    log("< " + line);

    if (line === "PONG") {
      log("Arduino communication verified.");
      return;
    }

    if (line.startsWith("DATA,")) {
      const parts = line.split(",");
      if (parts.length !== 8) return;

      const values = parts.slice(2).map(Number);
      if (values.some(v => !Number.isFinite(v))) return;

      values.forEach((v, i) => {
        $("a" + i).textContent = v;
      });

      history.push({
        time: new Date().toISOString(),
        values
      });
      if (history.length > 1000) history.shift();
      drawChart();
      return;
    }

    if (line.startsWith("STATUS,")) {
      $("safety-status").textContent = line;
    }

    if (line.startsWith("FAULT,")) {
      armed = false;
      $("safety-status").textContent = line;
      log("SAFETY EVENT: " + line);
    }
  }

  async function readLoop() {
    const decoder = new TextDecoder();

    try {
      while (port && port.readable) {
        reader = port.readable.getReader();

        try {
          while (true) {
            const {value, done} = await reader.read();
            if (done) break;
            lineBuffer += decoder.decode(value, {stream: true});

            let newline;
            while ((newline = lineBuffer.indexOf("\n")) >= 0) {
              const line = lineBuffer.slice(0, newline).trim();
              lineBuffer = lineBuffer.slice(newline + 1);
              handleLine(line);
            }
          }
        } finally {
          reader.releaseLock();
          reader = null;
        }
      }
    } catch (err) {
      log("Serial read error: " + err.message);
    }
  }

  async function connect() {
    if (!("serial" in navigator)) {
      log("Web Serial is unavailable. Use Chrome or Edge on HTTPS.");
      return;
    }

    try {
      // Must be called directly from the Connect button click.
      port = await navigator.serial.requestPort();
      await port.open({baudRate: 115200});

      writer = port.writable.getWriter();
      updateControls(true);
      setStatus("● Connected");
      log("USB serial connected at 115200 baud.");

      readTask = readLoop();

      await send("PING");
      await send("STATUS");
      await send("STREAM,1,250");

      heartbeatTimer = setInterval(() => {
        if (armed) send("HB");
      }, 500);

    } catch (err) {
      log("Connection failed: " + err.message);
      await disconnect();
    }
  }

  async function disconnect() {
    armed = false;
    clearInterval(heartbeatTimer);
    heartbeatTimer = null;

    try {
      if (writer) {
        await writer.write(new TextEncoder().encode("DISARM\n"));
        writer.releaseLock();
        writer = null;
      }
    } catch (err) {
      log("Could not send DISARM: " + err.message);
    }

    try {
      if (reader) await reader.cancel();
    } catch (_) {}

    try {
      if (port) await port.close();
    } catch (err) {
      log("Port close: " + err.message);
    }

    port = null;
    reader = null;
    updateControls(false);
    setStatus("● Disconnected");
    $("safety-status").textContent = "Disconnected. Outputs should be disarmed.";
  }

  $("connect").onclick = connect;
  $("disconnect").onclick = disconnect;

  $("arm").onclick = async () => {
    if (estop) {
      log("Reset E-STOP before arming.");
      return;
    }
    await send("ARM");
    armed = true;
    $("safety-status").textContent = "ARM command sent. Check Arduino acknowledgement.";
  };

  $("disarm").onclick = async () => {
    armed = false;
    await send("DISARM");
    $("safety-status").textContent = "Disarm command sent.";
  };

  $("estop").onclick = async () => {
    armed = false;
    estop = true;
    await send("ESTOP");
    $("safety-status").textContent = "EMERGENCY STOP command sent.";
  };

  $("reset").onclick = async () => {
    await send("RESET");
    estop = false;
    $("safety-status").textContent = "Reset command sent. Verify board status before arming.";
  };

  $("set-output").onclick = () =>
    send(`MODE,${$("digital-pin").value},OUT`);

  $("set-input").onclick = () =>
    send(`MODE,${$("digital-pin").value},IN`);

  $("digital-on").onclick = () =>
    send(`D,${$("digital-pin").value},1`);

  $("digital-off").onclick = () =>
    send(`D,${$("digital-pin").value},0`);

  $("pwm-slider").oninput = () => {
    $("pwm-value").textContent = $("pwm-slider").value;
  };

  $("send-pwm").onclick = () =>
    send(`PWM,${$("pwm-pin").value},${$("pwm-slider").value}`);

  $("download-csv").onclick = () => {
    const rows = ["timestamp,A0,A1,A2,A3,A4,A5"];
    history.forEach(row => {
      rows.push([row.time, ...row.values].join(","));
    });

    const blob = new Blob([rows.join("\n")], {type: "text/csv"});
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "arduino_sensor_data.csv";
    a.click();
    URL.revokeObjectURL(url);
  };

  updateControls(false);

  return () => {
    clearInterval(heartbeatTimer);
    if (reader) reader.cancel().catch(() => {});
    if (writer) writer.releaseLock();
    if (port) port.close().catch(() => {});
  };
}
"""

arduino_component = st.components.v2.component(
    name="arduino_usb_controller",
    html=HTML,
    css=CSS,
    js=JS,
)

arduino_component()
