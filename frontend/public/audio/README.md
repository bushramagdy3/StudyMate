Generated speech files go here.

Run this from the frontend folder while the backend is running:

```bash
npm run generate:speech
```

The script calls the backend `/api/tutor-speech` route, so the generated files
use the same TTS model and voice as dynamic speech.
