import torch
import torch.nn as nn

class ApoptoticLayer(nn.Module):
    """
    Simulates programmed layer death (apoptosis) for edge devices.
    Unloads the layer from memory if signal importance drops.
    """
    def __init__(self, core_layer, survival_threshold=0.05):
        super().__init__()
        self.core_layer = core_layer
        self.survival_threshold = survival_threshold
        self.is_apoptotic = False # Tracks if layer is "dead"

    def forward(self, x, signal_strength):
        # 1. If apoptosis already occurred, act as a pure identity block
        if self.is_apoptotic:
            return x
            
        # 2. Trigger programmed death if signal is too weak
        if signal_strength < self.survival_threshold:
            self._trigger_apoptosis()
            return x
            
        # 3. Otherwise, compute normally
        return self.core_layer(x)

    def _trigger_apoptosis(self):
        """Frees up VRAM dynamically on the factory floor."""
        del self.core_layer
        torch.cuda.empty_cache() 
        self.is_apoptotic = True
        print("Apoptosis triggered: Layer unloaded to conserve memory.")
