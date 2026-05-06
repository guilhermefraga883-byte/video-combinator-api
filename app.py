import os
import subprocess
import tempfile
import uuid
from flask import Flask, request, send_file, jsonify
from flask_cors import CORS

app = Flask(__name__)
CORS(app)

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
      - output_name: desired output filename (optional)
    Returns: combined MP4 file
    """
    try:
        if 'hook' not in request.files or 'content' not in request.files or 'cta' not in request.files:
            return jsonify({'error': 'Missing files. Need: hook, content, cta'}), 400

        job_id = str(uuid.uuid4())[:8]
        tmp = tempfile.mkdtemp()

        # Use original filenames for temp files to preserve codec hints
        hook_file    = request.files['hook']
        content_file = request.files['content']
        cta_file     = request.files['cta']

        hook_path    = os.path.join(tmp, f'hook_{job_id}.mp4')
        content_path = os.path.join(tmp, f'content_{job_id}.mp4')
        cta_path     = os.path.join(tmp, f'cta_{job_id}.mp4')
        list_path    = os.path.join(tmp, f'list_{job_id}.txt')
        out_path     = os.path.join(tmp, f'output_{job_id}.mp4')

        hook_file.save(hook_path)
        content_file.save(content_path)
        cta_file.save(cta_path)

        with open(list_path, 'w') as f:
            f.write(f"file '{hook_path}'\n")
            f.write(f"file '{content_path}'\n")
            f.write(f"file '{cta_path}'\n")

        # Get desired output name from request
        output_name = request.form.get('output_name', f'video_{job_id}')
        if not output_name.endswith('.mp4'):
            output_name += '.mp4'

        # Try fast stream copy first (no re-encode, very fast)
        result = subprocess.run([
            'ffmpeg', '-y',
            '-f', 'concat', '-safe', '0', '-i', list_path,
            '-c', 'copy',
            '-movflags', '+faststart',
            out_path
        ], capture_output=True, text=True, timeout=3600)  # 1 hour timeout

        # If copy failed (different codecs/resolutions), re-encode
        if result.returncode != 0:
            result = subprocess.run([
                'ffmpeg', '-y',
                '-f', 'concat', '-safe', '0', '-i', list_path,
                '-c:v', 'libx264', '-preset', 'fast', '-crf', '23',
                '-c:a', 'aac', '-b:a', '128k',
                '-movflags', '+faststart',
                out_path
            ], capture_output=True, text=True, timeout=3600)  # 1 hour timeout

        if result.returncode != 0:
            return jsonify({'error': 'FFmpeg failed', 'details': result.stderr[-2000:]}), 500

        return send_file(
            out_path,
            mimetype='video/mp4',
            as_attachment=True,
            download_name=output_name
        )

    except subprocess.TimeoutExpired:
        return jsonify({'error': 'Timeout: vídeo muito grande ou complexo'}), 504
    except Exception as e:
        return jsonify({'error': str(e)}), 500


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
