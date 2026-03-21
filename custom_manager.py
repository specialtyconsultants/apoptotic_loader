class MyRobotManager(ApoptoticManagerNode):

    def _execute_model_load(self) -> bool:
        """Load your model here."""
        self.model = torch.load('/opt/apoptotic/checkpoints/my_model.pt')
        return True

    def _execute_model_destroy(self):
        """Destroy your model state here. NO STATE CARRIES OVER."""
        del self.model
        torch.cuda.empty_cache()
        gc.collect()
