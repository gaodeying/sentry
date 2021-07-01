import {Fragment} from 'react';
import styled from '@emotion/styled';

import ExternalLink from 'app/components/links/externalLink';
import {t, tct} from 'app/locale';
import space from 'app/styles/space';
import {Event} from 'app/types/event';

type Props = {
  sdk: Event['sdk'];
  suggestion: NonNullable<Event['sdkUpdates']>[0];
  shortStyle?: boolean;
  capitalized?: boolean;
};

function getSdkUpdateSuggestion({
  sdk,
  suggestion,
  shortStyle = false,
  capitalized = false,
}: Props) {
  const getTitleData = () => {
    switch (suggestion.type) {
      case 'updateSdk': {
        const updateWord = capitalized ? t('Update') : t('update');
        return {
          href: suggestion?.sdkUrl,
          content: sdk
            ? shortStyle
              ? tct('[updateWord] to @v[new-sdk-version]', {
                  updateWord,
                  ['new-sdk-version']: suggestion.newSdkVersion,
                })
              : tct('[updateWord] your SDK from @v[sdk-version] to @v[new-sdk-version]', {
                  updateWord,
                  ['sdk-version']: sdk.version,
                  ['new-sdk-version']: suggestion.newSdkVersion,
                })
            : tct('[updateWord] your SDK version', {updateWord}),
        };
      }
      case 'changeSdk':
        return {
          href: suggestion?.sdkUrl,
          content: tct('migrate to the [sdkName] SDK', {
            sdkName: <code>{suggestion.newSdkName}</code>,
          }),
        };
      case 'enableIntegration':
        return {
          href: suggestion?.integrationUrl,
          content: t("enable the '%s' integration", suggestion.integrationName),
        };
      default:
        return null;
    }
  };

  const getTitle = () => {
    const titleData = getTitleData();

    if (!titleData) {
      return null;
    }

    const {href, content} = titleData;

    if (!href) {
      return content;
    }

    return <ExternalLink href={href}>{content}</ExternalLink>;
  };

  const title = <Fragment>{getTitle()}</Fragment>;

  if (!suggestion.enables.length) {
    return title;
  }

  const alertContent = suggestion.enables
    .map((subSuggestion, index) => {
      const subSuggestionContent = getSdkUpdateSuggestion({
        suggestion: subSuggestion,
        sdk,
      });
      if (!subSuggestionContent) {
        return null;
      }
      return <Fragment key={index}>{subSuggestionContent}</Fragment>;
    })
    .filter(content => !!content);

  if (!alertContent.length) {
    return title;
  }

  return tct('[title] so you can: [suggestion]', {
    title,
    suggestion: <AlertUl>{alertContent}</AlertUl>,
  });
}

export default getSdkUpdateSuggestion;

const AlertUl = styled('ul')`
  margin-top: ${space(1)};
  margin-bottom: ${space(1)};
  padding-left: 0 !important;
`;
