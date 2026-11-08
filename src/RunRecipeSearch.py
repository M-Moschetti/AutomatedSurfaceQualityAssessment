'''
Finds a polishing recipe for a material with RecipeSearch.py, on the RASI machine or as a simulation:

    python <repository>/src/RunRecipeSearch.py --network <RunName> --rates <9 µm> <3 µm> <1 µm> --depth <µm> [--sample <SampleName>]
                                               [--simulation --polished <folder> --scratched <folder> [--minimum <3 µm s> <1 µm s>]]

By default it runs on RASI: start it from the folder of the RASI control software (where mikroskop_jobs.json and
MicroscopeImages/ are), with the sample on the microscope. This needs the platform specific RASIMachine.py, which is not
part of this repository. A machine has the same three methods as SimulatedRASI: Polish(Trial), AcquireImages() and
ArchiveImages(Archive). The outputs are written to <repository>/src/Outputs/ regardless of the folder.

--simulation runs from any folder. It knows the "true" shortest 3 µm and 1 µm times (--minimum). A trial with at least
these times returns the images of the polished folder, any other trial those of the scratched folder; the images
themselves are classified by the network.
'''
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__))) # makes ClassifyImage, Modules etc. importable from any working directory
import ClassifyImage as CI
from RecipeSearch import RecipeGenerator, ControlVariables

class SimulatedRASI():
    # Polished images if the trial's 3 µm and 1 µm times reach the given minimum, otherwise scratched images
    def __init__(self, Minimum: dict, PolishedFolder: str, ScratchedFolder: str):
        self.Minimum, self.Polished, self.Scratched = Minimum, CI.FindImages(PolishedFolder), CI.FindImages(ScratchedFolder)

    def Polish(self, Trial: dict):
        self.Trial = Trial
        print(f"  [simulation] polish {', '.join(f'{Stage} {Seconds:g} s' for Stage, Seconds in Trial.items())}")

    def AcquireImages(self) -> list[str]:
        return self.Polished if all(self.Trial[Stage] >= Seconds for Stage, Seconds in self.Minimum.items()) else self.Scratched

    def ArchiveImages(self, Archive: str):
        pass # the simulated images are reused

def GenerateRecipe(Machine, Generator: RecipeGenerator) -> dict:
    # Trials until RecipeGenerator has found the recipe (or stops)
    Trial = Generator.FirstTrial()
    while True:
        Machine.Polish(Trial)
        Images = Machine.AcquireImages()
        Answer = Generator.Check(Images)
        print(f"Trial {Answer['Trial']}: {'polished' if Answer['Polished'] else 'not polished'} ({Answer['PolishedPercent']:.1f} % of the tiles) "
              f"-> {Answer['Decision']}: {Answer['Reason']}")
        Machine.ArchiveImages(f"{Generator.OutputPath}/Images/Trial{Answer['Trial']:02d}")
        if Answer["Decision"] != "Trial":
            return Answer
        Trial = Answer["NextTrial"]

def Main():
    Parser = argparse.ArgumentParser(description="Find a polishing recipe on the RASI machine or in a simulation.")
    Parser.add_argument("--network", required=True, help="Training run in src/Outputs/")
    Parser.add_argument("--sample", default="Sample", help="Sample name for the output folder")
    Parser.add_argument("--rates", type=float, nargs=3, required=True, metavar=("R9", "R3", "R1"), help="Removal rates of the 9, 3 and 1 µm stages [µm/s]")
    Parser.add_argument("--depth", type=float, required=True, help="Target removal depth per slice [µm]")
    Parser.add_argument("--simulation", action="store_true", help="Simulate the machine with folders of polished and scratched images")
    Parser.add_argument("--polished", help="Simulation: folder with images of a polished surface")
    Parser.add_argument("--scratched", help="Simulation: folder with images of a scratched surface")
    Parser.add_argument("--minimum", type=float, nargs=2, default=[45, 75], metavar=("T3", "T1"), help="Simulation: true shortest 3 and 1 µm times [s]")
    Arguments = Parser.parse_args()
    if Arguments.simulation and not (Arguments.polished and Arguments.scratched):
        Parser.error("--simulation needs --polished and --scratched")

    if Arguments.simulation:
        Machine = SimulatedRASI({"3um": Arguments.minimum[0], "1um": Arguments.minimum[1]}, Arguments.polished, Arguments.scratched)
    else:
        try:
            from RASIMachine import RASI
        except ImportError:
            sys.exit("Running on RASI needs src/RASIMachine.py, which is not part of this repository. Use --simulation instead.")
        Machine = RASI()
    Controls  = ControlVariables(RemovalRate9um_um_s=Arguments.rates[0], RemovalRate3um_um_s=Arguments.rates[1],
                                 RemovalRate1um_um_s=Arguments.rates[2], TargetDepth_um=Arguments.depth)
    Generator = RecipeGenerator(Arguments.network, Arguments.sample, Controls)
    try:
        Answer = GenerateRecipe(Machine, Generator)
    except SystemExit as Stop: # machine functions can end the program on errors, in one case with exit code 0
        sys.exit(f"The machine stopped the search (exit code {Stop.code}). Completed trials: {Generator.OutputPath}/Trials.csv")

    if Answer["Decision"] == "Done":
        print(f"Recipe {Answer['Recipe']['Polishing_s']} s: {Generator.OutputPath}/Recipe.json")
    else:
        print(f"No recipe ({Answer['Reason']}). Stop and keep the sample for inspection: {Generator.OutputPath}")
    # For a further sample, reuse the loaded network: RecipeGenerator(Arguments.network, "<next sample>", Controls, Classifier=Generator.Classifier)

if __name__ == "__main__":
    Main()
