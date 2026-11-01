import sys
import logging

logging.basicConfig(level=logging.WARNING, format="%(levelname)s: %(message)s")

try:
    import needle
    IS_SIMULATION = False
except ImportError:
    IS_SIMULATION = True
    class _StubNeedle:
        @staticmethod
        def tool(func):
            return func

        @staticmethod
        def run(prompt: str, **kwargs):
            return f"[Simulation] CLI processed: {prompt}"

    needle = _StubNeedle()

def main():
    mode_str = "SIMULATION" if IS_SIMULATION else "NATIVE"
    print("=" * 45)
    print(f"  Needle 3 CLI Interface [{mode_str} MODE]")
    print("  Type 'exit' or 'quit' to close.")
    print("=" * 45 + "\n")

    while True:
        try:
            user_input = input("You > ").strip()
            if not user_input:
                continue
            if user_input.lower() in ("exit", "quit"):
                print("Exiting...")
                break

            response = needle.run(user_input)
            
            if isinstance(response, dict):
                output = response.get("response", str(response))
            else:
                output = str(response)

            print(f"Needle > {output}\n")

        except (KeyboardInterrupt, EOFError):
            print("\nExiting...")
            break
        except Exception as e:
            print(f"Error executing command: {e}\n")

if __name__ == "__main__":
    main()