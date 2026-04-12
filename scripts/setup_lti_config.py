"""Generate lti_config.json for EduInsight after Moodle External Tool registration.

Usage:
    uv run python scripts/setup_lti_config.py --client-id CLIENT_ID [--deployment-id DEPLOYMENT_ID]

The Moodle platform URLs are auto-derived from MOODLE_LTI_PLATFORM_URL
(default: http://localhost:8080).
"""

import argparse
import json
import os

DEFAULT_PLATFORM_URL = "http://localhost:8080"


def main():
    parser = argparse.ArgumentParser(description="Generate lti_config.json for EduInsight")
    parser.add_argument("--client-id", required=True, help="Client ID from Moodle External Tool config")
    parser.add_argument("--deployment-id", default="1", help="Deployment ID (default: 1)")
    parser.add_argument(
        "--platform-url",
        default=os.environ.get("MOODLE_LTI_PLATFORM_URL", DEFAULT_PLATFORM_URL),
        help=f"Moodle base URL (default: {DEFAULT_PLATFORM_URL})",
    )
    args = parser.parse_args()

    platform_url = args.platform_url.rstrip("/")

    # Moodle LTI 1.3 platform endpoints
    config = {
        platform_url: [
            {
                "default": True,
                "client_id": args.client_id,
                "auth_login_url": f"{platform_url}/mod/lti/auth.php",
                "auth_token_url": f"{platform_url}/mod/lti/token.php",
                "auth_audience": None,
                "key_set_url": f"{platform_url}/mod/lti/certs.php",
                "key_set": None,
                "deployment_ids": [args.deployment_id],
            }
        ]
    }

    output_path = os.path.join(
        os.path.dirname(__file__), "..", "src", "eduinsight", "lti_config.json"
    )
    output_path = os.path.normpath(output_path)

    with open(output_path, "w") as f:
        json.dump(config, f, indent=2)

    print(f"LTI config written to {output_path}")
    print(f"Platform: {platform_url}")
    print(f"Client ID: {args.client_id}")
    print(f"Deployment ID: {args.deployment_id}")
    print()
    print("EduInsight endpoints for Moodle:")
    print("  Tool URL:      http://localhost:8000/lti/launch")
    print("  Login URL:     http://localhost:8000/lti/login")
    print("  JWKS URL:      http://localhost:8000/lti/jwks")
    print("  Redirect URIs: http://localhost:8000/lti/launch")


if __name__ == "__main__":
    main()
