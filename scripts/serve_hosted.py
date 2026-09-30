"""One API process and one persistent workspace; Render supplies PORT and TLS."""
import os
from pathlib import Path

import uvicorn

from kaizen.api.app import create_app

if __name__ == '__main__':
    uvicorn.run(create_app(ui_dir=Path('/app/ui/dist')), host='0.0.0.0', port=int(os.environ.get('PORT', '10000')), workers=1)
