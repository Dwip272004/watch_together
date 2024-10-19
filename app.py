import os
import sqlite3
import random
from flask import Flask, render_template, request, redirect, url_for, send_from_directory, jsonify
from flask_socketio import SocketIO, emit, join_room
from werkzeug.utils import secure_filename
from gevent.pywsgi import WSGIServer  # Import Gevent's WSGI server

# Initialize the Flask app and SocketIO
app = Flask(__name__)
app.config['UPLOAD_FOLDER'] = os.path.join(os.path.abspath(os.path.dirname(__file__)), 'static', 'videos')
app.secret_key = 'falcons'
socketio = SocketIO(app)

# Get the absolute path for the SQLite database
DATABASE_PATH = os.path.join(os.path.abspath(os.path.dirname(__file__)), 'videos.db')

# SQLite database setup
def init_db():
    with app.app_context():  # Ensure the app context is active
        conn = sqlite3.connect(DATABASE_PATH)
        cursor = conn.cursor()

        # Create tables for videos and rooms
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS videos (
                id INTEGER PRIMARY KEY AUTOINCREMENT, 
                filename TEXT
            )
        ''')
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS rooms (
                id INTEGER PRIMARY KEY AUTOINCREMENT, 
                room_code TEXT UNIQUE, 
                video_filename TEXT, 
                creator_username TEXT
            )
        ''')  # Updated table to include creator_username

        conn.commit()
        conn.close()

# Home route to display the create/join options
@app.route('/')
def index():
    return render_template('home.html')

# Route to handle video upload and room creation
@app.route('/create', methods=['GET', 'POST'])
def create_room():
    if request.method == 'POST':
        creator_username = request.form.get('username')  # Get the creator's username

        if 'video' not in request.files:
            return jsonify({'error': 'No video file provided'}), 400

        video = request.files['video']

        if video.filename == '':
            return jsonify({'error': 'No selected file'}), 400

        if video:
            filename = secure_filename(video.filename)

            # Check if the directory exists, and create it if not
            if not os.path.exists(app.config['UPLOAD_FOLDER']):
                os.makedirs(app.config['UPLOAD_FOLDER'])

            # Save the video file
            video.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))

            # Generate a unique 4-digit room code
            room_code = str(random.randint(1000, 9999))

            # Store the room and video information in the database
            with app.app_context():  # Ensure the app context is active
                conn = sqlite3.connect(DATABASE_PATH)
                cursor = conn.cursor()
                cursor.execute('INSERT INTO rooms (room_code, video_filename, creator_username) VALUES (?, ?, ?)', 
                               (room_code, filename, creator_username))  # Save creator_username
                conn.commit()
                conn.close()

            # Redirect to the watch room with the generated code
            return redirect(url_for('watch_room', room_code=room_code))

    return render_template('create.html')

# Route to join an existing room by room code
@app.route('/join', methods=['GET', 'POST'])
def join_room_route():
    if request.method == 'POST':
        room_code = request.form['room_code']

        # Check if the room code exists
        with app.app_context():  # Ensure the app context is active
            conn = sqlite3.connect(DATABASE_PATH)
            cursor = conn.cursor()
            cursor.execute('SELECT video_filename, creator_username FROM rooms WHERE room_code = ?', (room_code,))
            room = cursor.fetchone()
            conn.close()

        if room:
            return redirect(url_for('watch_room', room_code=room_code))
        else:
            return jsonify({'error': 'Room not found'}), 404

    return render_template('join.html')

# Watch the video in the room (sync with WebSocket)
@app.route('/watch/<room_code>')
def watch_room(room_code):
    # Get the video associated with the room code
    with app.app_context():  # Ensure the app context is active
        conn = sqlite3.connect(DATABASE_PATH)
        cursor = conn.cursor()
        cursor.execute('SELECT video_filename, creator_username FROM rooms WHERE room_code = ?', (room_code,))
        room = cursor.fetchone()
        conn.close()

    if room:
        video_filename, creator_username = room
        return render_template('watch.html', video=video_filename, room_code=room_code, creator_username=creator_username)
    else:
        return jsonify({'error': 'Room not found'}), 404

# Serve the uploaded video file
@app.route('/videos/<filename>')
def uploaded_video(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)

# WebSocket events to sync video controls (play, pause, seek)
@socketio.on('play_video')
def play_video(data):
    emit('play_video', room=data['room_code'], broadcast=True)

@socketio.on('pause_video')
def pause_video(data):
    emit('pause_video', room=data['room_code'], broadcast=True)

@socketio.on('seek_video')
def seek_video(data):
    emit('seek_video', data, room=data['room_code'], broadcast=True)

# WebSocket connection event
@socketio.on('join')
def on_join(data):
    room_code = data['room_code']
    join_room(room_code)
    emit('user_joined', {'room_code': room_code}, room=room_code)

# Additional logic to handle playback control by creator only
@socketio.on('control_video')
def control_video(data):
    room_code = data['room_code']
    action = data['action']
    current_username = data['current_username']
    creator_username = data['creator_username']
    
    # Check if the current user is the creator
    if current_username != creator_username:
        emit('error', {'message': 'You do not have permission to control the video.'}, room=request.sid)
        return
    
    # If the action is valid, emit the respective control events
    if action == 'play':
        emit('play_video', room=room_code, broadcast=True)
    elif action == 'pause':
        emit('pause_video', room=room_code, broadcast=True)


if __name__ == '__main__':
    init_db()  # Initialize the SQLite database
    port = int(os.environ.get('PORT', 5000))  # Get the port from environment variables or use 5000
    http_server = WSGIServer(('0.0.0.0', port), app)  # Create a WSGI server with Gevent
    http_server.serve_forever()  # Start the server
