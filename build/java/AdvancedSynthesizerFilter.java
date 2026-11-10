/* LanguageTool, a natural language style checker
 * Copyright (C) 2020 Daniel Naber (http://www.danielnaber.de)
 *
 * This library is free software; you can redistribute it and/or
 * modify it under the terms of the GNU Lesser General Public
 * License as published by the Free Software Foundation; either
 * version 2.1 of the License, or (at your option) any later version.
 *
 * This library is distributed in the hope that it will be useful,
 * but WITHOUT ANY WARRANTY; without even the implied warranty of
 * MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
 * Lesser General Public License for more details.
 *
 * You should have received a copy of the GNU Lesser General Public
 * License along with this library; if not, write to the Free Software
 * Foundation, Inc., 51 Franklin St, Fifth Floor, Boston, MA  02110-1301
 * USA
 *
 * Изменено в 2026 году, Razhon (build/java/AdvancedSynthesizerFilter.java): замены с несинтезированным {suggestion}
 * убираются (docs/rules/Unify_PADJ_NN_number.md, вариант 2.2).
 */
// образ: sha256 0c4e5112a9e318eabe0eaa30a4aef50139d6779f4c7044c16d61ca5b4b997c14 /LanguageTool/org/languagetool/rules/ru/AdvancedSynthesizerFilter.class

package org.languagetool.rules.ru;

import java.io.IOException;
import java.util.List;
import java.util.Map;
import java.util.stream.Collectors;

import org.languagetool.AnalyzedTokenReadings;
import org.languagetool.rules.AbstractAdvancedSynthesizerFilter;
import org.languagetool.rules.RuleMatch;

/*
 * Synthesize suggestions using the lemma from one token (lemma_from)
 * and the POS tag from another one (postag_from).
 *
 * The lemma_select and postag_select attributes are required
 * to choose one among several possible readings.
 */
public class AdvancedSynthesizerFilter extends AbstractAdvancedSynthesizerFilter {
  @Override
  public RuleMatch acceptRuleMatch(RuleMatch match, Map<String, String> arguments, int patternTokenPos,
                                   AnalyzedTokenReadings[] patternTokens, List<Integer> tokenPositions) throws IOException {
    RuleMatch m = super.acceptRuleMatch(match, arguments, patternTokenPos, patternTokens, tokenPositions);
    if (m == null) {
      return null;
    }
    // синтез не дал формы: родительский класс возвращает замечание с буквальным {suggestion} в замене
    List<String> ok = m.getSuggestedReplacements().stream()
        .filter(r -> !r.toLowerCase().contains("{suggestion}"))
        .collect(Collectors.toList());
    if (ok.size() != m.getSuggestedReplacements().size()) {
      m.setSuggestedReplacements(ok);
    }
    return m;
  }
}
