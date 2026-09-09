Add-Type -AssemblyName System.Speech
$synth = New-Object System.Speech.Synthesis.SpeechSynthesizer
$synth.Rate = 0
$synth.Volume = 100
$text = [char]0x6211 + [char]0x7231 + [char]0x4f60
$synth.Speak($text)
Write-Output SPEAK_DONE
