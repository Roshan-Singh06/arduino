
import streamlit as st
import serial
import serial.tools.list_ports
import pandas as pd
import plotly.express as px
import time
from datetime import datetime

st.set_page_config(
    page_title="Arduino Universal Controller",
    page_icon="⚙️",
    layout="wide"
)

if "ser" not in st.session_state:
    st.session_state.ser = None

if "records" not in st.session_state:
    st.session_state.records = []

if "armed" not in st.session_state:
    st.session_state.armed = False

if "estop" not in st.session_state:
    st.session_state.estop = False

if "logs" not in st.session_state:
    st.session_state.logs = []

if "last_hb" not in st.session_state:
    st.session_state.last_hb = 0.0


def send(cmd):
    ser = st.session_state.ser

    if ser and ser.is_open:
        ser.write((cmd + "\n").encode())
        st.session_state.logs.append(
            f"TX: {cmd}"
        )
        return True

    return False


def read_serial():

    ser = st.session_state.ser

    if not ser or not ser.is_open:
        return

    while ser.in_waiting:

        line = ser.readline().decode(
            errors="ignore"
        ).strip()

        if not line:
            continue

        st.session_state.logs.append(
            f"RX: {line}"
        )

        if line == "ACK,ARMED":
            st.session_state.armed = True

        elif line in ("ACK,DISARMED", "ACK,ESTOP", "ACK,RESET"):
            st.session_state.armed = False

            if line == "ACK,ESTOP":
                st.session_state.estop = True

            if line == "ACK,RESET":
                st.session_state.estop = False

        elif line.startswith("FAULT,"):

            st.session_state.armed = False

            if "WATCHDOG" in line:
                st.error("Arduino watchdog triggered")

        elif line.startswith("DATA,"):

            v = line.split(",")

            if len(v) == 8:
                try:
                    st.session_state.records.append({
                        "Timestamp": datetime.now().isoformat(),
                        "Time_ms": int(v[1]),
                        **{
                            f"A{i}": int(v[i + 2])
                            for i in range(6)
                        }
                    })

                    st.session_state.records = (
                        st.session_state.records[-20000:]
                    )

                except ValueError:
                    pass


st.title("⚙️ Arduino Universal Control Center")

st.caption("Arduino Uno | USB | Digital / Analog / PWM")

# CONNECTION
st.sidebar.header("USB Connection")

ports = [
    p.device
    for p in serial.tools.list_ports.comports()
]

port = st.sidebar.selectbox(
    "COM Port",
    ports if ports else ["No device found"]
)

if st.sidebar.button("CONNECT"):

    try:
        if st.session_state.ser:
            st.session_state.ser.close()

        st.session_state.ser = serial.Serial(
            port,
            115200,
            timeout=0.02
        )

        time.sleep(2)
        st.session_state.ser.reset_input_buffer()

        st.sidebar.success("Connected")

    except Exception as e:
        st.sidebar.error(str(e))


if st.sidebar.button("DISCONNECT"):

    if st.session_state.ser:
        st.session_state.ser.close()

    st.session_state.ser = None
    st.session_state.armed = False


ser = st.session_state.ser

st.divider()

# SAFETY
st.subheader("Controller Safety")

c1, c2, c3 = st.columns(3)

c1.metric(
    "USB",
    "CONNECTED" if ser and ser.is_open else "OFFLINE"
)

c2.metric(
    "OUTPUTS",
    "ARMED" if st.session_state.armed else "DISARMED"
)

c3.metric(
    "ESTOP",
    "ACTIVE" if st.session_state.estop else "CLEAR"
)

a, b, c = st.columns(3)

with a:
    if st.button("ARM", disabled=not bool(ser)):
        send("ARM")

with b:
    if st.button("DISARM", disabled=not bool(ser)):
        send("DISARM")

with c:
    if st.button("EMERGENCY STOP", type="primary",
                 disabled=not bool(ser)):
        send("ESTOP")

if st.button("RESET EMERGENCY STOP"):
    send("RESET")


# DIGITAL CONTROL
st.divider()
st.subheader("Digital Pin Control")

pin = st.selectbox(
    "Digital Pin",
    list(range(2, 14))
)

mode = st.selectbox(
    "Pin Mode",
    ["IN", "OUT"]
)

if st.button("Configure Pin"):
    if not st.session_state.armed:
        send(f"MODE,{pin},{mode}")
    else:
        st.warning("Disarm before changing pin mode.")

x, y = st.columns(2)

with x:
    if st.button("DIGITAL HIGH",
                 disabled=not st.session_state.armed):
        send(f"D,{pin},1")

with y:
    if st.button("DIGITAL LOW",
                 disabled=not st.session_state.armed):
        send(f"D,{pin},0")

if st.button("READ DIGITAL"):
    send(f"READ,{pin}")


# PWM
st.divider()
st.subheader("PWM Control")

pwm_pin = st.selectbox(
    "PWM Pin",
    [3, 5, 6, 9, 10, 11]
)

pwm_value = st.slider(
    "PWM Value",
    0, 255, 0
)

st.write(f"Duty command: {pwm_value / 255 * 100:.1f}%")

if st.button("APPLY PWM",
             disabled=not st.session_state.armed):
    send(f"PWM,{pwm_pin},{pwm_value}")


# DATA ACQUISITION
st.divider()
st.subheader("Automatic Analog Acquisition")

interval = st.select_slider(
    "Sampling interval (ms)",
    options=[100, 200, 500, 1000, 2000, 5000],
    value=200
)

x, y = st.columns(2)

with x:
    if st.button("START ACQUISITION"):
        send(f"STREAM,1,{interval}")

with y:
    if st.button("STOP ACQUISITION"):
        send("STREAM,0")


# LIVE MONITOR
@st.fragment(run_every=0.25)
def live_monitor():

    if not st.session_state.ser or not st.session_state.ser.is_open:
        st.warning("Connect Arduino first.")
        return

    # Heartbeat
    now = time.monotonic()

    if st.session_state.armed:
        if now - st.session_state.last_hb > 0.5:
            if send("HB"):
                st.session_state.last_hb = now

    read_serial()

    if st.session_state.records:

        df = pd.DataFrame(st.session_state.records)
        latest = df.iloc[-1]

        cols = st.columns(6)

        for i, col in enumerate(cols):
            col.metric(f"A{i}", int(latest[f"A{i}"]))

        channels = st.multiselect(
            "Analog Channels",
            [f"A{i}" for i in range(6)],
            default=["A0", "A1"]
        )

        if channels:
            fig = px.line(
                df.tail(500),
                x="Time_ms",
                y=channels
            )

            st.plotly_chart(
                fig,
                use_container_width=True
            )

    st.subheader("Serial Communication Log")

    for entry in st.session_state.logs[-15:]:
        st.text(entry)


live_monitor()


# TERMINAL
st.divider()
st.subheader("Serial Terminal")

terminal = st.text_input(
    "Command",
    placeholder="PING"
)

if st.button("SEND COMMAND"):

    allowed = [
        "PING", "STATUS", "ARM",
        "DISARM", "ESTOP", "RESET",
        "STREAM,0"
    ]

    if terminal.strip() in allowed:
        send(terminal.strip())
    else:
        st.warning(
            "Use the dashboard controls for pin commands. "
            "Terminal currently accepts status and safety commands."
        )


# CSV
st.divider()
st.subheader("Experiment Data")

if st.session_state.records:

    df = pd.DataFrame(st.session_state.records)

    st.download_button(
        "DOWNLOAD CSV",
        df.to_csv(index=False),
        "arduino_data.csv",
        "text/csv"
    )
