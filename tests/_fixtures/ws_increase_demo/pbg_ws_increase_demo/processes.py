from process_bigraph import Process


class IncreaseProcess(Process):
    """Trivial linear-growth process for the explorer test fixture."""
    config_schema = {'rate': {'_type': 'float', '_default': 1.0}}

    def inputs(self):
        return {'level': 'float'}

    def outputs(self):
        return {'level': 'float'}

    def update(self, state, interval=1.0):
        rate = (self.config or {}).get('rate', 1.0)
        return {'level': state.get('level', 0.0) * rate}
