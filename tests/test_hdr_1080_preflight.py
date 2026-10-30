"""Private 1080p experiment fails closed without fresh resource evidence."""
import importlib
import sys
import types
import unittest
import v2_bootstrap

name='ComfyUI_zura_nodes.artist_studio'
if name not in sys.modules:
    module=types.ModuleType(name);module.__path__=[str(v2_bootstrap.ROOT/'artist_studio')];sys.modules[name]=module
check=importlib.import_module('ComfyUI_zura_nodes.artist_studio.hdr_1080_preflight')


class HDR1080PreflightTests(unittest.TestCase):
    def valid(self):
        return dict(width=1920,height=1080,frames=25,available_ram=32*check.GIB,
                    total_vram=16000*check.MIB,free_vram=14500*check.MIB,
                    temp_free=10*check.GIB,output_free=10*check.GIB,queue_idle=True)

    def test_exact_thresholds_select_only_measured_configuration(self):
        result=check.check_1080_experiment(**self.valid())
        self.assertEqual((result['padded_frames'],result['temporal_window'],result['vae_temporal_size'],result['vae_temporal_overlap']),(25,17,32,8))
        self.assertTrue(result['experimental'])
        for frames in (18,24,25):
            self.assertEqual(check.check_1080_experiment(**{**self.valid(),'frames':frames})['padded_frames'],25)

    def test_unmeasured_shapes_lengths_and_ambiguous_queue_are_rejected(self):
        for update in ({'width':1918},{'height':1920},{'frames':17},{'frames':26},{'frames':True},{'queue_idle':False},{'queue_idle':None}):
            with self.subTest(update=update),self.assertRaises(ValueError):check.check_1080_experiment(**{**self.valid(),**update})

    def test_each_missing_low_or_inconsistent_resource_fails(self):
        cases=[('available_ram',check.MIN_AVAILABLE_RAM-1,'system RAM'),
               ('total_vram',check.MIN_TOTAL_VRAM-1,'GPU'),
               ('free_vram',check.MIN_FREE_VRAM-1,'GPU'),
               ('free_vram',17000*check.MIB,'GPU'),
               ('temp_free',check.MIN_DISK-1,'storage'),
               ('output_free',check.MIN_DISK-1,'storage'),
               ('available_ram',None,'verify'),('free_vram',float('nan'),'verify'),('temp_free',True,'verify')]
        for key,value,message in cases:
            with self.subTest(key=key,value=value),self.assertRaisesRegex(ValueError,message):
                check.check_1080_experiment(**{**self.valid(),key:value})

    def test_low_memory_signal_targets_only_the_callers_active_prompt(self):
        self.assertTrue(check.should_cancel_for_memory(check.CRITICAL_AVAILABLE_RAM-1,own_prompt_running=True))
        self.assertFalse(check.should_cancel_for_memory(check.CRITICAL_AVAILABLE_RAM,own_prompt_running=True))
        self.assertFalse(check.should_cancel_for_memory(0,own_prompt_running=False))
        self.assertFalse(check.should_cancel_for_memory(0,own_prompt_running=None))
        with self.assertRaisesRegex(ValueError,'verified'):
            check.should_cancel_for_memory(None,own_prompt_running=True)


if __name__=='__main__':unittest.main()
