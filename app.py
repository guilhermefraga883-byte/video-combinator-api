import os
import subprocess
import tempfile
import uuid
from flask import Flask, request, send_file, jsonify
from flask_cors import CORS

app = Flask(__name__)
CORS(app)  # Allow all origins

UPLOAD_FOLDER = tempfile.gettempdir()

@app.route('/health', methods=['GET'])
def health():
    return jsonify({'status': 'ok'})

@app.route('/combine', methods=['POST'])
def combine():
    """
    Expects multipart/form-data with:
      - hook: video file
      - content: video file
      - cta: video file
    Returns: combined MP4 file
    """
    try:
        if 'hook' not in request.files or 'content' not in request.files or 'cta' not in request.files:
            return jsonify({'error': 'Missing files. Need: hook, content, cta'}), 400

        job_id = str(uuid.uuid4())[:8]
        tmp = tempfile.mkdtemp()

        hook_path    = os.path.join(tmp, 'hook.mp4')
        content_path = os.path.join(tmp, 'content.mp4')
        cta_path     = os.path.join(tmp, 'cta.mp4')
        list_path    = os.path.join(tmp, 'list.txt')
        out_path     = os.path.join(tmp, f'output_{job_id}.mp4')

        request.files['hook'].save(hook_path)
        request.files['content'].save(content_path)
        request.files['cta'].save(cta_path)

        with open(list_path, 'w') as f:
            f.write(f"file '{hook_path}'\n")
            f.write(f"file '{content_path}'\n")
            f.write(f"file '{cta_path}'\n")

        # Try fast copy first (same codec)
        result = subprocess.run([
            'ffmpeg', '-y',
            '-f', 'concat', '-safe', '0', '-i', list_path,
            '-c', 'copy',
            '-movflags', '+faststart',
            out_path
        ], capture_output=True, text=True)

        # If copy failed, re-encode (handles different codecs/resolutions)
        if result.returncode != 0:
            result = subprocess.run([
                'ffmpeg', '-y',
                '-f', 'concat', '-safe', '0', '-i', list_path,
                '-c:v', 'libx264', '-preset', 'fast', '-crf', '23',
                '-c:a', 'aac', '-b:a', '128k',
                '-movflags', '+faststart',
                out_path
            ], capture_output=True, text=True)

        if result.returncode != 0:
            return jsonify({'error': 'FFmpeg failed', 'details': result.stderr}), 500

        return send_file(out_path, mimetype='video/mp4', as_attachment=True,
                         download_name=f'video_{job_id}.mp4')

    except Exception as e:
        return jsonify({'error': str(e)}), 500


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
