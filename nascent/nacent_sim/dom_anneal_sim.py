#!/usr/bin/env python
# -*- coding: utf-8 -*-
##    Copyright 2015 Rasmus Scholer Sorensen, rasmusscholer@gmail.com
##
##    This program is free software: you can redistribute it and/or modify
##    it under the terms of the GNU General Public License as published by
##    the Free Software Foundation, either version 3 of the License, or
##    (at your option) any later version.
##
##    This program is distributed in the hope that it will be useful,
##    but WITHOUT ANY WARRANTY; without even the implied warranty of
##    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
##    GNU General Public License for more details.
##
##    You should have received a copy of the GNU General Public License
##    along with this program.  If not, see <http://www.gnu.org/licenses/>.

# pylint: disable=W0142,C0103,C0301,W0141


"""

Concept:
* Step-wise statistical thermodynamic annealing simulation.
* Simular to multi-strand, but using *domains* rather than bases.
* The hybridization energy (dG) of a domain is determined by a finite number of state permutations:
** For each of the two strands:
** Whther the domain has a neighboring domain (danling penalty).
** Whether the neighboring domain is hybridized (stacking gain).
    Note: The stacking gain can only be used once per side: Even if both strands has both neighboring domains
    hybridized, you only get one stacking gain for each side.
** The change in system entropy caused by the hybridization:
    Combining two complexes to one will decrease the combined entropy of the two complexes.
    Joining the ends of a complex might also decrease rotational freedom of the complex -> entropy reduction.
* Molar concentrations are not an explicit part of the thermodynamic calculations, but are accounted for
    through the interaction probability: If molecule 1 is present in 5 copies and molecule 2 only present in 1 copy,
    and both has the same interaction energy, then molecule 1 has 5 times higher probability than molecule 2
    of being selected as the next "winner".

Questions:
* How to account for intra-molecular reactions? - Hybridizations within a complex?
** Effect on hybridization energy: Depends on whether hybridization will restrict rotational freedom, etc.
** Effect on interaction probability? Increase "effective" concentration vs increase in -dG?
    I think increase in -dG is the better option as this allows us to treat all interactions "equally".
    (I.e. not having to say: If this domain interacts with that domain, then the domain is in 1000x concentration,
    but otherwise it is in 1x concentration.)


Calculating domain hybridization energy for a specific strand:
* Find the "global" dG lookup table for the domain, indexed by the 8-bit-tuple:
    (strand1: (<5p-domain>, <5p-domain-is-hybridized>, <3p-domain>, <3p-domain-is-hybridized),
     strand1: (<5p-domain>, <5p-domain-is-hybridized>, <3p-domain>, <3p-domain-is-hybridized))
*


How to calculate interaction probability?
* Statistical mechanics/physics
* Partition function: Z = sum(exp(-E(q)/(k*T)) for all q)
* Probability of state q: P(q) = exp(-E(q)/(k*T) / Z

How to select which domain will hybridize next?
a) First select a domain based on interaction probability, then select a strand with that domain?
b) Enter all domains of all strands into the lottery, weighted by -dG.
    Perhaps consider all "events" that could possibly happen.
    Uh, if you have 10 strands with domain A and 5 strands with the complementary domain a, that's 50 possible events..
    It might scale considerably better if you just say "all identical domains are treated as one".

Edit: New random model
1) Select a random domain.
2) If the domain is not hybridized: select a rcomplement domain at random.
    The selection has to be at least partially biased against the number/concentration of rcomplement domains.
    Intra-complex reactions should be biased higher.
    In particular, there should be a chance that no rcomplement domain is selected (and nothing will happen).
        Hybridization rate = k * [A] * [a]
21) An alternative way is to select two domains at random and check whether they are complementary.
    However, that is expensive (lots of failed picks).
    Actually, since selection of the rcomplement domain above must be scaled, that might be the same...
        - Except that intra-complex reactions will have higher chance of success.
            And taking that into account is easier if we have already selected the first one..
    Hybridized domains could still be checked whenever they are picked.
3) Calculate the energy difference and partition function for hybridized vs melted state
    of the domain and it's partner.
        E = (look up energy in domain dG table or calculate anew)
    Q: How to properly account for entropy?
        We have already done the random selection, which affects the k_on rate.
    Q: For intra-complex reactions, how much entropy is accounted for by
        "increased effective concentration" and how much must be adjusted in the energy function?
        - The k_off rate must be correct. k_off does not depend on changes to effective concentration.
4) Roll a dice, and change state of the domain and its partner if the dice says so.




Are you considering domain A and it complement, a, seperately?
* YES: Because every strand with domain A is considered separately, thus A and a must also be considered separately.
* NO : A domain hybridization is one event, A hybridizing to a is the same as a hybridizing to A.
    You could say that you are only considering all capital A and their interactions with all lower-case a,
    and not considering all lowercase a and their interaction with capital A.


How to account for events that would occour on different time scales?
* Multistrand selects an event, then forwards the clock by the characteristic time of that event..
    Not sure this would be realistic when we have multiple species in the reaction tube.
* Maybe just consider "sufficiently large" time steps?
    This might dis-favour formations that rely on a lot of fast steps.
* Perhaps not worry too much about this just yet...


Reversability:
* Should I allow domains to melt and dissociate?
* Perhaps add this through a modification to selection method (b) above: consider domain
    melting as an "event", similar to hybridization.


Some calculations:
* Consider a volume of 1 um^3 = (1e-5 dm)^3 = 1e-15 L = 1 femto-liter.
* For c = 1 nM: n = 1e-15 L * 1e-9 mol/L = 1e-24 mol = 0.6
    N_Avogagro = 6.02e23 /mol


"""

#import sys
import os
import random
#from random import choice
from collections import defaultdict
#from math import log, exp

import numpy as np

from .dom_anneal_models import Tube #, Strand, Domain, Complex
from .energymodels.biopython import binary_state_probability, hybridization_dH_dS


N_AVOGADRO = 6.022e23   # /mol


class Simulator():
    """
    Simulator class to hold everything required for a single simulation.
    """

    def __init__(self, volume, strands, params, verbose=0, domain_pairs=None,
                 outputstatsfiles=None):
        """
        outputstatsfiles : A dict of <stat type>: <outputfilename>
        """
        self.Tube = Tube(volume, strands)
        self.Volume = volume
        self.Strands = strands
        self.VERBOSE = verbose
        self.Print_statsline_when_saving = params.get('print_statsline_when_saving', False)
        # random.choice requires a list, not a set.
        self.Domains_list = [domain for strand in strands for domain in strand.Domains]
        self.Domains = set(self.Domains_list)
        self.N_domains = len(self.Domains)
        self.N_strands = len(self.Strands)
        self.N_domains_hybridized = sum(1 for domain in self.Domains_list if domain.Partner)
        self.N_strands_hybridized = sum(1 for oligo in self.Strands if oligo.is_hybridized())
        self.Domains_by_name = defaultdict(list)
        for d in self.Domains:
            self.Domains_by_name[d.Name].append(d)
        if domain_pairs is None:
            domain_pairs = {d.Name: d.lower() if d.Name == d.upper() else d.upper() for d in self.Domains_list}
        assert not any(k == v for k, v in domain_pairs.items())
        self.Domain_pairs = domain_pairs
        self.Uppers = [d for d in self.Domains if d == d.upper()]
        self.Lowers = [d for d in self.Domains if d == d.lower()]
        self.Params = params
        # Standard enthalpy and entropy of hybridization,
        # indexed as [<domain-name-uppercase>][0 or 1]
        self.Domain_dHdS = {}
        #self.Visualization_hook = self.print_domain_hybridization_percentage
        #self.Visualization_hook = self.randomly_print_stats
        self.Default_statstypes = ("timesampling", "changesampling")
        self.Visualization_hook = None # self.save_stats_if_large

        if isinstance(outputstatsfiles, str):
            base, ext = os.path.splitext(outputstatsfiles)
            outputstatsfiles = {k: base+"_"+k+ext for k in self.Default_statstypes}
        self.Outputstatsfiles = outputstatsfiles    # dict with <stats type>: <outputfilepath> entries
        self.Record_stats = params.get("record_stats", True)    # Enable or disable stats recording
        # Record stats every N number of steps.
        self.Timesampling_frequency = self.Params.get('timesampling_frequency', 10)
        self.N_steps = 0    # Total number of steps
        self.N_changes = 0  # Number of state changes (hybridizations or de-hybridizations)
        # Save stats to a cache and only occationally append them to file on disk.
        # Stats_cache: dict <stats type>: <stats>, where stats is a list of tuples:
        # [(Temperature, N_dom_hybridized, %_dom_hybridized, N_oligos_hybridized, %_oligos_hybridized), ...]
        self.Stats_cache = {k: [] for k in self.Default_statstypes}

        print("Simulator initiated at V=%s with %s strands spanning %s domains." \
              % (self.Volume, len(self.Strands), len(self.Domains)))
        c = 1/N_AVOGADRO/self.Volume
        print("Concentration of each domain is: %0.3g M" % c)
        print("Domain pairing map:", ", ".join("->".join(kv) for kv in self.Domain_pairs.items()))



    def n_hybridized_domains(self):
        """ Count the number of hybridized domains. """
        count = sum(1 for domain in self.Domains_list if domain.Partner)
        if not count % 2 == 0:
            print("Weird - n_hybridized_domains counts to %s (should be an even number)" % count)
            print("Hybridized domains:", ", ".join(str(domain) for domain in self.Domains_list if domain.Partner))
        return count

    def n_hybridized_strands(self):
        """ Count the number of hybridized strands. """
        return sum(1 for oligo in self.Strands if oligo.is_hybridized())


    def get_complexes_and_strands(self):
        """ Return all complexes and strands that are in a complex. """
        complexed_strands = [strand for strand in self.Strands if strand.Complex]
        complexes = {strand.Complex for strand in complexed_strands}
        return complexed_strands, complexes


    def select_event_domains(self, oversampling=1):
        """
        Returns a tuple with (domain1, domain2).
        If domain2 is None, then no
        """
        is_hybridized = None
        dom1 = random.choice(self.Domains_list)
        if dom1.Partner:
            return (dom1, dom1.Partner, True)

        ## Note: The steps speed up considerably when reaching low temperatures where most domains are hybridized.
        ## That indicates that the steps below takes up considerable computation time.
        ## I imagine calling d.effective_activity when calculating domain_weights takes considerable time.
        ## However, this should only be slow when the two domains are in the same complex and we have to calculate
        ## the distance between the two domains.
        ## Note sure about np.random.choice(...), but I imagine that is fairly fast.
        ## OK, think I optimized it a bit. Now simulations slows down when there are lots of state *changes*.

        # Only consider domains that are not already paired up:
        candidates = [d for d in self.Domains_by_name[self.Domain_pairs[dom1.Name]] if not d.Partner]
        # Whether we find a candidate depends on (1) the number of candidates and (2) the volume.
        # empty_volume_number should be scaled with the tube volume.
        # empty_volume_number = self.Params.get("empty_volume_number", 100)
        # Edit: Using volume and numbers to get an actual concentration:
        # c2 = 1/N_AVOGADRO/self.Volume     # Edit2: concentration is determined for each domain individually.

        # Need to scale intra-complex domain higher: (higher effective concentration)
        # Doing this by making a list with repeated entries:
        # (This is only able to scale by integers, but should suffice for now...)
        #if dom1.Complex and any(dom1.Complex == d.Complex for d in candidates):
        #    candidates = sum(([d]*d.effective_conc(dom1) if d.Complex == dom1.Complex else [d]
        #                      for d in candidates), []) # Need to give a list as starting value to sum

        # Simple way: just add the two together (then we won't have to worry about len(candidates) >= empty_volume_number)
        # If empty_volume_number = 0, there should be 100% chance of selecting a candidate, so subtract 1:
        #n_cands = len(candidates)
        #event_number = random.randint(0, empty_volume_number + len(candidates) - 1)
        # More complex: empty_volume_number is the "total volume" of which the domains can occupy a certain portion.
        #if len(candidates) < empty_volume_number:
        #    event_number = random.randint(0, empty_volume_number)
        #    # event_number = random.randint(0, empty_volume_number - len(candidates)) # No...?
        #else:
        #    # Will most likely never happen
        #    event_number = random.randint(0, len(candidates) - 1)
        #if event_number >= len(candidates):
        #    # Nothing should happen, dom1 did not find a partner in the "allotted time".
        #    return (dom1, None)
        #dom2 = candidates[event_number]


        ### New concentration-based weighting and selection:

        domain_weights = [d.effective_activity(dom1, volume=self.Volume, oversampling=oversampling)
                          for d in candidates]


        # Do you add a specific "water/None" option?
        # Or do you first calculate "is a domain gonna be selected?" and then select which domain is selected?
        domain_weights_sum = sum(domain_weights)
        # Adding a specific "None" option:
        if domain_weights_sum < 1:
            domain_weights.append(1-domain_weights_sum)
            candidates.append(None)
        # http://docs.scipy.org/doc/numpy/reference/generated/numpy.random.choice.html
        if domain_weights_sum > 1:
            # Normalize...:
            domain_weights = [w/domain_weights_sum for w in domain_weights]
        dom2 = np.random.choice(candidates, p=domain_weights)
        return dom1, dom2, is_hybridized


    def hybridization_energy(self, domain1, domain2, T):
        """
        Calculate standard Gibbs free energy of hybridization between domain1 and domain2,
        assuming that domain1 and domain2 does not form any other structures in their single-stranded state.
        Note that this assumption does often not hold true.

        Is there a linear or just simple dependence for dG on temperature?
        Note: The values of DNA_NN tables are in
            kcal/mol for enthalpy  (the first entry)
            cal/mol/K for entropy  (the second entry)
        The Nearest Neighbor model calculates ΔG° as:
            ΔG°(total) = ΔG°(init) + ΔG°(symmetry) + sum(ΔG°(stacking)) + ΔG°(AT terminal)
        The stacking parameters are given as DNA_NN3:
            e.g. AA/TT is for the stacking between AA
                                                   TT
            The directionality does not seem to matter, e.g. 5'-AC is same as 5'-CA.
        Where the Gibbs free energy is (assuming ΔCp° = 0, so ΔH° and ΔS° are temperature independent):
            ΔG° = ΔH° - T*ΔS°
        This means you can contract all entropy terms:
            ΔG°(total) = ΔH°(init) + ΔH°(symmetry) + sum(ΔH°(stacking)) + ΔH°(AT terminal)
                        - T * (ΔS°(init) + ΔS°(symmetry) + sum(ΔS°(stacking)) + ΔS°(AT terminal))
                       = ΔH°(total) - T*ΔS°(total)
        If you have saved ΔH°(total) and ΔS°(total), then calculating ΔG°(total) is fast.
        It would, perhaps, be nice to have the updated values from David Zhang..
        """
        # returned is (5p domain-exists, 5p domain-hybridized, 3p domain-exists, 3p domain-hybridized)
        # d1_params, d2_params = domain1.neighbor_state_tuple(), domain2.neighbor_state_tuple()
        # param_tuple = d1_params + d2_params
        # indexed as [<domain-name-uppercase>][<8-bit-tuple>][0 or 1]
        # Edit: Currently just saving the dH_dS result as [<domain-name-uppercase>]
        # and performing neighbor-induced adjustments on the fly...
        # Do not use dict.setdefault(key, energy-if-no-key()) for this!
        # This will call energy-if-no-key() before checking whether keys is in the dict.
        if domain1.Name not in self.Domain_dHdS:
            deltaH, deltaS = self.Domain_dHdS[domain1.Name] = hybridization_dH_dS(domain1.Sequence, domain2.Sequence)
        else:
            deltaH, deltaS = self.Domain_dHdS[domain1.Name]

        ### Dangling adjustment from electrostatic repulsion ###
        # Seems like this should be sequence dependent, based on DNA_DE1 lookup table.
        # There is even a difference whether a nucleotide is on the 5p end or 3p... sigh...
        # Use dG = dH - dS*T with T = 330 K (57 C) to get a feeling for the contributions.
        # According to the DNA_DE1 table, dangling ends actually repel primarily via entropic effects?
        # - both dH and dS are negative.
        # Actually, it seems most dangling ends contribute a negative ΔΔG to hybridization energy:
        # DE_dG = {k: (v[0]-0.300*v[1], v[0]-0.360*v[1]) for k, v in DNA_DE1.items()}   # from about 30 C to 90 C:
        # [pyplot.plot([300, 360], v) for v in DE_dG.values()]  # followed by display(*getfigs()), with %pylab enabled
        # In all cases the ΔΔG is between -1 and +1 kcal/mol.
        # FWIW, -1 kcal/mol corresponds to a change in K of exp(-ΔG/RT) = exp(ΔS/R-ΔH/RT) = 4.6
        # At 60 C: RT = 1.987 cal/mol/K * 330 K = 0.65 kcal/mol.
        # Hmm... It also seems to me that the effect of electrostatic repulsion should be salt dependent.
        N_neighbors = sum(bool(n) for n in
                          (domain1.domain5p(), domain2.domain3p(),
                           domain2.domain5p() or domain1.domain3p()))
        deltaH_corr = -3.0 * N_neighbors    #  -3 cal/mol   electrostatic repulsion for each neighboring domain
        deltaS_corr = -10.0 * N_neighbors   # -10 cal/mol/K electrostatic repulsion for each neighboring domain
        # Domain repulsion: ΔΔG of 0 kcal/mol at 300 K (30 C) and +0.4 kcal/mol at 340 K (70 C) - seems reasonable.

        # Stacking interactions when the neighboring domain is hybridized:
        # Again, this should probably be sequence dependent:
        N_stacking = (domain1.domain5p_is_hybridized() or domain2.domain3p_is_hybridized() +
                      domain2.domain5p_is_hybridized() or domain1.domain3p_is_hybridized())
        # A CG/GC NN has dH, dS: 'CG/GC': (-10.6, -27.2), while AT/TA has: 'AT/TA': (-7.2, -20.4)
        deltaH_corr += -7.0 * N_stacking    # -10 cal/mol/K for each stacking interaction
        deltaS_corr += -20.0 * N_stacking   # -20 cal/mol   for each stacking interaction
        # Stacking: ΔΔG of -1 kcal/mol at 300 K (30 C) and -0.2 kcal/mol at 340 K (70 C) - seems reasonable.

        # It is probably a lot better to compare the two states directly using NuPack...!
        # (or at least see what they do and do the same...)

        # ΔG° = ΔH° - T*ΔS°             # Standard Gibbs free energy
        # ΔG = ΔG° + RT ln(Q)           # Gibbs free energy at non-equilibrium
        # ΔG° = ΔH° - T*ΔS° = -RT ln(K) # At equilibrium ΔG=0. Notice the minus in front of RT!

        # You may want to correct the deltaS depending on how the hybridization connects the strands.
        # I.e. how domain hybridization will affect the overall entropy of the complex.
        #  - strand hybridization will reduce the conformational freedom of the complex.
        # This is a dynamic function of the current complex structure and cannot be stored for later use.
        # Obviously, this is only applicable if the two domains are already in the same complex.
        if domain1.Complex == domain2.Complex:
            deltaS_corr += 4

        # Add corrigating factors
        deltaH += deltaH_corr
        deltaS += deltaS_corr

        # The deltaH and deltaS calculated by melting_dH_dS is based on SantaLucia1997 - DNA_NN3.
        # The initial entropy of formation are rather negligible.
        deltaG = deltaH*1000 - T * deltaS    # Values in cal/mol - rather than kcal/mol

        return deltaG, deltaH, deltaS, deltaH_corr, deltaS_corr





    def hybridization_probability(self, domain1, domain2, T, Q=None):
        """
        Calculate the partition

        SantaLucia, Dirks (Ann Rev Biophys, 2004): "We note that the database presented is not appropriate
        for partition function computations (50; J. SantaLucia, unpublished results)." - WTF?
        Ahh... they are only good for determining Tm.. Not for partition functions far from Tm.
            - The most likely reason is that either there's some ensemble effects that are not properpy captured
            by the NN models, or the values are just not accurate enough for partition calculations.

        SantaLucia, Dirks (Ann Rev Biophys, 2004): "Note that many duplexes have competing single-strand structure,
        and this compromises the validity of the two-state approximation and results in systematically lower TMs than
        would be predicted by Equation 3 [the equation used to predict Tm]."

        Perhaps I should look at how NuPack calculates its partition functions...
        NuPack refs:
            http://www.nupack.org/home/model
            "The free energy of an unpseudoknotted secondary structure is calculated using nearest-neighbor empirical
            parameters for RNA in 1M Na+ (Serra and Turner, 1995; Mathews et al., 1999) or DNA in user-specified
            Na+ and Mg++ concentrations (SantaLucia, 1998; SantaLucia and Hicks, 2004; Koehler and Peyret, 2005)"
        """
        deltaG, deltaH, deltaS, deltaH_corr, deltaS_corr = \
            self.hybridization_energy(domain1, domain2, T)    # return value in cal/mol
        #R = 1.987  # universal gas constant in cal/mol/K
        ## Note: R = k * NA , where k is the boltzmann constant and NA is Avogadro's constant.
        #K = exp(-deltaG/(R*T))
        ## Not really sure how to convert from equilibrium constant K to probability that they will hybridize
        ##   the deltaG used to calculate the equilibrium constant is at standard conditions (1 M) !
        ## Probably refer to NuPack or similar to make sure you get it right...
        ## Also remember that K = k_on/k_off
        ##                         k_on              [1/M/s]      # v_on = k_on [strandA] [strandB]
        ##     domainA + domainB --------> duplex
        ##                       <--------
        ##                         k_off             [1/s]       # v_off = k_off [duplex]
        #if domain1.Complex and domain2.Complex and domain1.Complex == domain2.Complex:
        #    # What if we are breaking the bond, and the bond is the only bond holding the domains in the same complex?
        #    # Well, that is a k_off rate, that shouldn't be affected by concentrations anyways.
        #    c = 1
        #else:
        #    # Different complexes
        #    # 1 nM is about 1 molecule per femto-liter: c = 1 nM: n = 1e-15 L * 1e-9 mol/L = 1e-24 mol = 0.6
        #    # N_Avogadro = 6.022e23/mol
        #    c = 1/N_Avogadro/self.Volume
        #
        ## Fuck that, I can't see how to include the concentration in the probability.
        ## As I see it, it should already be included
        #p = K/(1+K)     # If K = 7/2, then p = 7/(7+2) = K/(K+1) = 1/(1+1/K)
        #
        ## Edit: How to include concentration in probability:
        ## 1) Calculate non-standard ΔG: ΔG = ΔG° + RT ln(Q)
        ##       where Q = [duplex]/([strandA] [strandB])    # If concentrations are around 1 uM, then Q = 1e6.

        # Note that the concentration is obviously very important. If you have a duplex at T=Tm (so p_duplex = 50%),
        # at a concentration of 1 uM. If you then increase the concentration/activity to 1 M, then suddenly
        # the p_duplex is something like 99.9998 % !
        # Another way to see this is to compare Tm at c = 25 nM with Tm at c = 1 M.
        # -- typically increases about 30 degC !!
        # If you want to simulate this, then you need to incorporate this at the earlier "selection" step.
        # This essentially boils down to setting a very high empty_volume_number in select_event_domains() above.
        # Alternatively, you can use a lower empty_volume_number (and thus get more selections), but
        # then you have to compensate using a correcting Q.
        # For instance, instead of saying "we put the strands so close together that they have an activity of 1",
        # you could say, "we put them within a distance so their concentrations are 1 mM", and then give Q = 1e3.
        # Note: Requiring an activity of 1 before hybridization can occour might be way too high:
        # DNA strands has a certain extend, and can interact at great distances.
        # Of course, they have to eventually end up in a duplex state, where we can assume an activity of 1...
        # But that might still yield kinetics that are quite wrong.. Maybe they don't have an activity of 1 in the
        # duplex state?
        # Note: There is also a certain probability that the standard ΔH°, ΔS°, and ΔG° values are not suited for
        # these types of partition calculations (they've stated that them self).
        # Again: Try to look at what NuPack does.
        # Edit: Essentially, we just need to assure that at T=Tm, p_on == p_off.
        # p_on is defined at two stages: selection and hybridization (after it has been selected).
        #       p_on = p_selection * p_hyb
        # There are only two easy ways to guarantee that you get the correct p_on:
        # 1) set p_selection = 1 -- and use concentration to calculate Q which is then used when calculating p_hyb.
        # 2) Use concentration to calculate p_selection, and use the same p_hyb for both hybridization and melting.
        #
        # Another concern is that for low concentrations (1 uM - 1 nM), p_on and p_off will both be very, very
        # low -- like 1 in a millionth to 1 in a billionth. This requires a lot of fruitless "dice rolling",
        # before the system actually changes state. And that is at T=Tm...
        # One way to mitigate this is to do oversampling (or whatever it should be called):
        # Multiplying both p_on and p_off by a certain probablity_oversampling_factor, to ensure that something
        # actually happens within a reasonable timeframe.
        # The thing here is that you need to take state into account:
        # If the strand/domain is currently hybridized, you need to increase the chance that it will melt.
        # If it is not currently hybridized, then increase the chance that it (1) find a partner,
        # (2) to which it will hybridize.
        if Q is None:
            Q = 1   # Do selection in select_event_domains()
            #Q = 1e3 # select_event_domains() selects to 1 mM.
            #Q = 1e6 # select_event_domains() selects to 1 uM.
            # Q = (concentration) # If p_selection = 1
        p_hyb = binary_state_probability(deltaG, T, Q=Q)

        return p_hyb


    def step(self, T):
        """
        Perform a single step in the simulation at temperature T.
        """
        oversampling = self.Params['probablity_oversampling_factor']
        domain1, domain2, is_hybridized = self.select_event_domains(oversampling=oversampling)
        if not domain2:
            # If we are selecting for an activity of 1 (or equal to the duplex activity, whatever that is),
            # then there must be a very high probability of NOT finding a domain2. Like, 1 in a million..
            # And, similarly, if we have a duplex, there is a 100% chance of selecting that duplex, but
            # then, even at T=Tm, there is only a 1 in a million chance that the duplex will melt.
            # In other words, we have to perform a lot of "selections" before two strands will hybridize,
            # and we have to perform a lot of p_hyb < random.random() tests before a duplex will melt.
            # This may or may not be suitable for simulation.
            # Also, as you can see, it becomes important that the selection probability is correct
            # (given that p_hyb is close to 1 once two strands have been selected).
            # Instead of trying to get the selection probability right, it might be more reliable
            # to delegate this part to hybridization_probability() using Q to correct for non-unity activity.
            # This will still get a lot of failed attempts, failing at p < random.random() instead of during
            # duplex2 selection, but it is probably a lot easier to get right for a novice like me :)
            # https://en.wikipedia.org/wiki/Thermodynamic_activity
            #print("Failed to select a 2nd domain for domain 1.")
            #sys.stdout.write(".")  # No, even this is too much.
            return

        # Assertion check (at least while we are still debugging and ensuring compliancy).
        # Eventually we might allow self-complementary domains... (I.e. two different domain objects but with same name)
        assert domain1 != domain2 and domain1.Name != domain2.Name

        p_hyb = self.hybridization_probability(domain1, domain2, T)
        if self.VERBOSE > 2:
            print("\nSelected domain 1 and 2:", domain1, domain2)
            # Probability that the two strands are in hybridized state:
            print("- Hybridization probability:", p_hyb)
        if is_hybridized and oversampling:
            # If duplexes are hybridized, increase p_off by decreasing p_hyb:
            p_hyb = 1 - oversampling*(1-p_hyb)
            # If duplexes are not hybridized, probablity_oversampling_factor is applied during domain selection.

        ## Change hybridization state, depending on p_hyb and a dice roll:
        # p_hyb will typically be very close to 1.0 (e.g. 0.999997), since we assume Q=1 after domain selection
        # (although oversampling might reduce this slightly)
        if p_hyb < random.random():
            # Dices say that domains should be henceforth be in *de-hybridized* state:
            if is_hybridized:
                if self.VERBOSE > 1:
                    print("- DE-HYBRIDIZING domain 1 and 2 (%s and %s)" % (domain1, domain2))
                # assert self.n_hybridized_domains() == self.N_domains_hybridized
                domain1.dehybridize(domain2)
                self.N_changes += 1
                self.N_domains_hybridized -= 2
                # assert self.n_hybridized_domains() == self.N_domains_hybridized
                if self.Record_stats:
                    self.record_stats_snapshot(T)
                if self.Visualization_hook:
                    self.Visualization_hook(updated_domains=(domain1, domain2))
            else:
                if self.VERBOSE > 0:
                    print("- Domain 1 (%s) did not hybridize to domain2 (%s) (p_hyb = %s) [rare event]" % \
                        (domain1, domain2, p_hyb))
        else:
            # Dices say that domains should be henceforth be in *hybridized* state:
            if is_hybridized:
                if self.VERBOSE > 2:
                    print("- Domain1 REMAINS HYBRIDIZED to domain2 (%s ... %s)" % (domain1, domain2))
            else:
                # HYBRIDIZE:  (separate this logic out)
                if self.VERBOSE > 1:
                    print("- HYBRIDIZING domain 1 and 2 (%s and %s)" % (domain1, domain2))
                # assert self.n_hybridized_domains() == self.N_domains_hybridized
                domain1.hybridize(domain2)
                self.N_changes += 1
                self.N_domains_hybridized += 2
                # assert self.n_hybridized_domains() == self.N_domains_hybridized
                if self.Record_stats:
                    self.record_stats_snapshot(T)
                if self.Visualization_hook:
                    self.Visualization_hook(updated_domains=(domain1, domain2))



    def simulate(self, T, n_steps_max=100000):
        """
        Simulate at most n_steps number of rounds at temperature T.
        """
        assert self.n_hybridized_domains() == self.N_domains_hybridized
        n_done = 0
        while n_done < n_steps_max:
            try:
                self.step(T)
            except AssertionError as e:
                print("AssertionError:", e)
                print("self.n_hybridized_domains(), self.N_domains_hybridized = %s, %s" % \
                      (self.n_hybridized_domains(), self.N_domains_hybridized))
                raise(e)
            n_done += 1
            self.N_steps += 1
            if n_done % 10000 == 0:
                print("Simulated %s of %s steps at T=%s K (%s state changes in %s total steps)" % \
                      (n_done, n_steps_max, T, self.N_changes, self.N_steps))
            if self.Record_stats and (self.N_steps % self.Timesampling_frequency == 0):
                self.record_stats_snapshot(T, statstype="timesampling")
        assert self.n_hybridized_domains() == self.N_domains_hybridized


    def anneal(self, T_start, T_finish, delta_T=-1, n_steps_per_T=100000):
        """
        Simulate annealing repeatedly from T_start to T_finish,
        decreasing temperature by delta_T for every round,
        doing at most n_steps number of steps at each temperature.
        # TODO: I am currently only capturing stats whenever the state changs (hybridization/melting).
        # This means that if we only have two states, those two states will be equally represented in the data,
        # even though one state might be favored and system spends the majority of the total time in this state.
        # It would probably be nice to also capture "time-interspersed" snapshots, so that I can distinguish this.
        """

        # Range only useful for integers...
        T = T_start
        assert delta_T != 0
        assert T_start > T_finish if delta_T < 0 else T_finish > T_start
        while T >= T_finish if delta_T < 0 else T <= T_finish:
            print("\nSimulating at %s K for %s steps (ramp is %s K to %s K in %s K increments)" % \
                  (T, n_steps_per_T, T_start, T_finish, delta_T))
            self.simulate(T, n_steps_per_T)
            T += delta_T
            self.save_stats_cache() # Save cache once per temperature


    def save_stats_if_large(self, **kwargs):
        """ Save stats cache when it is sufficiently large. """
        if any(len(cache) > 10000 for cache in self.Stats_cache.values()):
            self.save_stats_cache()

    def save_stats_cache(self, outputfilenames=None):
        """ Save stats cache to outputfn. """
        if self.Print_statsline_when_saving:
            print("| Total domain hybridization percentage: {:.0%} ({} of {})".format(
                self.N_domains_hybridized/self.N_domains,
                self.N_domains_hybridized, self.N_domains))
            #print(", ".join(str(i) for i in self.Stats_cache[-1]))
        if outputfilenames is None:
            outputfilenames = self.Outputstatsfiles
        if not outputfilenames:
            print("Unable to save stats cache: outputstatsfile is:", outputfilenames)
            return
        for statstype, outputfn in outputfilenames.items():
            with open(outputfn, 'a') as fp:
                # self.Stats_cache = [(Temperature, N_doms_hybridized, %_doms_hybridized), ...]
                fp.write("\n".join(", ".join(str(i) for i in line) for line in self.Stats_cache[statstype])+"\n")
            self.Stats_cache[statstype] = []    # Reset the cache


    def record_stats_snapshot(self, T, statstype="changesampling"):
        """ Save stats snapshot to stats cache. """
        self.Stats_cache[statstype].append((T,
                                            self.N_domains_hybridized,
                                            self.N_domains_hybridized/self.N_domains,
                                            self.N_strands_hybridized,
                                            self.N_strands_hybridized/self.N_strands
                                           ))


    def randomly_print_stats(self, **kwargs):
        """ Print stats at random intervals. """
        if random.random() < 0.05:
            self.print_domain_hybridization_stats(**kwargs)


    def print_domain_hybridization_stats(self, updated_domains=None):
        """ Print domain hybridization stats """
        N_domains = len(self.Domains)
        N_hybridized = sum(1 for domain in self.Domains if domain.Partner)
        if self.VERBOSE > 1:
            print("| - Updated domains %s and %s" % updated_domains)
        print("| Total domain hybridization percentage: {:.0%} ({} of {})".format(
            N_hybridized/N_domains, N_hybridized, N_domains))





if __name__ == '__main__':

    import os
    from .dom_utils import parse_strand_domains_file

    strand_defs_file = os.path.join(os.path.dirname(__file__), "testfiles", "strand_defs01.txt")
    input_oligos = parse_strand_domains_file(strand_defs_file)

    # Some calculations:
    # * Consider a volume of 1 um^3 = (1e-5 dm)^3 = 1e-15 L = 1 femto-liter.
    # * For c = 1 nM: n = 1e-15 L * 1e-9 mol/L = 1e-24 mol = 0.6
    #     N_Avogagro = 6.02e23 /mol

    #
    adhoc_params = {}
    simulator = Simulator(volume=1e-15, strands=input_oligos, params=adhoc_params)
